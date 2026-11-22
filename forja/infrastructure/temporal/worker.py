"""Worker e cliente do DeliveryWorkflow."""

from __future__ import annotations

from collections.abc import Sequence

from temporalio.client import Client, WorkflowHandle
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError
from temporalio.worker import Interceptor, Worker

from forja.application.comandos import (
    Aprovar,
    Confirmar,
    CriarIntent,
    OrigemExterna,
    Rejeitar,
    Sinalizacao,
)
from forja.application.portas.entregas import ResultadoInicio
from forja.domain.intent import Origem, TipoDeOrigem, intent_id_de
from forja.infrastructure.github.cliente import slugificar
from forja.infrastructure.temporal.activities import DeliveryActivities
from forja.infrastructure.temporal.workflows import (
    DeliveryEntrada,
    DeliverySaida,
    DeliveryWorkflow,
    workflow_id,
)

FILA_PADRAO = "forja-delivery"
LIMITE_CORPO = 8000


def criar_worker(
    client: Client,
    activities: DeliveryActivities,
    task_queue: str = FILA_PADRAO,
    interceptors: Sequence[Interceptor] = (),
    max_cached_workflows: int = 1000,
) -> Worker:
    ativ = activities
    return Worker(
        client,
        task_queue=task_queue,
        workflows=[DeliveryWorkflow],
        activities=[
            ativ.executar_etapa,
            ativ.publicar_comentario,
            ativ.commitar_artefato,
            ativ.ler_artefato,
            ativ.abrir_pr,
            ativ.registrar_desfecho,
        ],
        interceptors=list(interceptors),
        max_cached_workflows=max_cached_workflows,
    )


async def iniciar_ou_sinalizar(
    client: Client, entrada: DeliveryEntrada, task_queue: str = FILA_PADRAO
) -> tuple[WorkflowHandle[DeliveryWorkflow, DeliverySaida], bool]:
    """Inicia o workflow da intenção; se já existe, vira sinal. Devolve (handle, novo)."""
    wid = workflow_id(entrada.intent_id)
    try:
        handle = await client.start_workflow(
            DeliveryWorkflow.run,
            entrada,
            id=wid,
            task_queue=task_queue,
            id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
        )
        return handle, True
    except WorkflowAlreadyStartedError:
        handle = client.get_workflow_handle_for(DeliveryWorkflow.run, wid)
        await handle.signal(DeliveryWorkflow.intencao_repetida)
        return handle, False


class TemporalEntregaGateway:
    """Adaptador da porta `EntregaGateway` sobre o Temporal; o id do workflow é o intent_id."""

    def __init__(
        self, client: Client, task_queue: str = FILA_PADRAO, prazo_lembrete_s: float = 48 * 3600
    ) -> None:
        self._client = client
        self._fila = task_queue
        self._prazo = prazo_lembrete_s

    @staticmethod
    def _id(origem: OrigemExterna, titulo: str = "-") -> str:
        return intent_id_de(
            Origem(TipoDeOrigem.ISSUE_GITHUB, origem.repositorio, str(origem.numero), titulo)
        )

    async def iniciar(self, comando: CriarIntent) -> ResultadoInicio:
        entrada = DeliveryEntrada(
            intent_id=self._id(comando.origem, comando.titulo),
            prazo_lembrete_s=self._prazo,
            repositorio=comando.origem.repositorio,
            numero=comando.origem.numero,
            titulo=comando.titulo[:300],
            slug=slugificar(comando.titulo),
            url=comando.origem.url,
            corpo=comando.corpo[:LIMITE_CORPO],
        )
        _, novo = await iniciar_ou_sinalizar(self._client, entrada, self._fila)
        return "iniciada" if novo else "ja_existia"

    async def parar(self, origem: OrigemExterna) -> bool:
        handle = self._client.get_workflow_handle(self._id(origem))
        try:
            await handle.signal(DeliveryWorkflow.parar)
        except RPCError:
            return False
        return True

    async def sinalizar(self, comando: Sinalizacao) -> bool:
        handle = self._client.get_workflow_handle(self._id(comando.origem))
        try:
            match comando:
                case Confirmar():
                    await handle.signal(DeliveryWorkflow.confirmar, comando.autor)
                case Aprovar():
                    await handle.signal(DeliveryWorkflow.aprovar, comando.autor)
                case Rejeitar():
                    await handle.signal(
                        DeliveryWorkflow.rejeitar, args=[comando.autor, comando.motivo]
                    )
        except RPCError:
            return False
        return True

    async def cancelar_todas(self) -> int:
        total = 0
        async for wf in self._client.list_workflows(
            'WorkflowType="DeliveryWorkflow" AND ExecutionStatus="Running"'
        ):
            await self._client.get_workflow_handle(wf.id).signal(DeliveryWorkflow.parar)
            total += 1
        return total
