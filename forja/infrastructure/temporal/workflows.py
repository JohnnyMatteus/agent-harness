"""DeliveryWorkflow: um workflow por intenção, com sinais de confirmação e parada.

Código de workflow precisa ser determinístico; todo efeito externo fica em activities.
As transições vêm do agregado `Entrega` do domínio; o workflow só as dispara.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from forja.domain.entrega import Entrega
    from forja.domain.estados import Estado, RaioDeImpacto
    from forja.infrastructure.temporal.activities import EtapaEntrada, EtapaSaida, PublicarEntrada


class Desfecho(StrEnum):
    CONCLUIDA = "concluida"
    CANCELADA = "cancelada"


@dataclass(frozen=True)
class DeliveryEntrada:
    intent_id: str
    # Prazo do lembrete de aprovação (configuração; o design doc cita 48 h como exemplo).
    prazo_lembrete_s: float = 48 * 3600
    timeout_etapa_s: float = 3600
    heartbeat_s: float = 30
    # Origem da intenção. Titulo e corpo são texto não confiável (dado, nunca instrução).
    repositorio: str = ""
    numero: int = 0
    titulo: str = ""
    corpo: str = ""


@dataclass
class DeliverySaida:
    intent_id: str
    desfecho: Desfecho
    etapa_final: str
    etapas_executadas: list[str] = field(default_factory=list[str])
    lembretes: int = 0
    sinais_repetidos: int = 0


def workflow_id(intent_id: str) -> str:
    """Id determinístico: o próprio intent_id (ADR 0030), um workflow por intenção."""
    return intent_id


@workflow.defn(name="DeliveryWorkflow")
class DeliveryWorkflow:
    def __init__(self) -> None:
        self._entrega: Entrega | None = None
        self._confirmado = False
        self._parar = False
        self._lembretes = 0
        self._repetidos = 0
        self._executadas: list[str] = []

    @workflow.signal
    def confirmar(self) -> None:
        self._confirmado = True

    @workflow.signal
    def parar(self) -> None:
        self._parar = True

    @workflow.signal
    def intencao_repetida(self) -> None:
        """Evento repetido da mesma intenção vira sinal, nunca execução nova."""
        self._repetidos += 1

    @workflow.query
    def etapa_atual(self) -> str:
        return self._entrega.estado.value if self._entrega else Estado.PLAN.value

    @workflow.query
    def lembretes_registrados(self) -> int:
        return self._lembretes

    @workflow.run
    async def run(self, entrada: DeliveryEntrada) -> DeliverySaida:
        corpo = asyncio.ensure_future(self._percorrer(entrada))
        parada = asyncio.ensure_future(workflow.wait_condition(lambda: self._parar))
        try:
            await workflow.wait([corpo, parada], return_when=asyncio.FIRST_COMPLETED)
            if corpo.done() and not self._parar:
                try:
                    corpo.result()
                except BaseException:
                    await self._desfecho("erro")
                    raise
                desfecho = Desfecho.CONCLUIDA
                await self._desfecho("concluida")
            else:
                corpo.cancel()
                await asyncio.gather(corpo, return_exceptions=True)
                desfecho = Desfecho.CANCELADA
        except asyncio.CancelledError:
            # Cancelamento pelo servidor equivale ao sinal "parar".
            corpo.cancel()
            await asyncio.gather(corpo, return_exceptions=True)
            desfecho = Desfecho.CANCELADA
        finally:
            parada.cancel()
        return DeliverySaida(
            intent_id=entrada.intent_id,
            desfecho=desfecho,
            etapa_final=self.etapa_atual(),
            etapas_executadas=list(self._executadas),
            lembretes=self._lembretes,
            sinais_repetidos=self._repetidos,
        )

    async def _percorrer(self, entrada: DeliveryEntrada) -> None:
        entrega = self._entrega = Entrega(intent_id=entrada.intent_id)
        await self._etapa_plan(entrada)
        await self._aguardar_confirmacao(entrada)
        entrega.confirmar_intent()
        while entrega.estado is not Estado.MAINTAIN:
            await self._executar(entrada, entrega.estado.value)
            self._avancar(entrega)

    async def _executar(self, entrada: DeliveryEntrada, etapa: str) -> EtapaSaida:
        saida: EtapaSaida = await workflow.execute_activity(
            "executar_etapa",
            EtapaEntrada(
                intent_id=entrada.intent_id,
                etapa=etapa,
                repositorio=entrada.repositorio,
                numero=entrada.numero,
                titulo=entrada.titulo,
                corpo=entrada.corpo,
            ),
            result_type=EtapaSaida,
            start_to_close_timeout=timedelta(seconds=entrada.timeout_etapa_s),
            heartbeat_timeout=timedelta(seconds=entrada.heartbeat_s),
            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        self._executadas.append(saida.etapa)
        return saida

    async def _publicar(self, entrada: DeliveryEntrada, corpo: str, chave: str) -> None:
        """Só o workflow escreve no GitHub (ADR 0007); a activity é idempotente pela chave."""
        await workflow.execute_activity(
            "publicar_comentario",
            PublicarEntrada(
                entrada.repositorio, entrada.numero, corpo, f"{entrada.intent_id}:{chave}"
            ),
            result_type=str,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )

    async def _desfecho(self, desfecho: str) -> None:
        await workflow.execute_activity(
            "registrar_desfecho",
            desfecho,
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

    async def _etapa_plan(self, entrada: DeliveryEntrada) -> None:
        """No M1 a etapa Plan é o agente eco: roda no sandbox e o workflow publica a resposta."""
        saida = await self._executar(entrada, Estado.PLAN.value)
        if saida.texto and entrada.repositorio:
            await self._publicar(entrada, f"**Forja (eco)**\n\n{saida.texto}", "plan")

    @staticmethod
    def _avancar(entrega: Entrega) -> None:
        """Caminho feliz do esqueleto do M1; verificação e review reais vêm depois."""
        match entrega.estado:
            case Estado.DESIGN:
                entrega.concluir_spec(pontos_em_aberto=0)
            case Estado.BUILD:
                entrega.concluir_build()
            case Estado.TEST:
                entrega.registrar_verificacao(verde=True)
            case Estado.REVIEW:
                entrega.concluir_review(achados_bloqueantes=False, raio=RaioDeImpacto.BAIXO)
            case Estado.DEPLOY:
                entrega.concluir_deploy()
            case _:
                raise ApplicationError(f"estado sem avanço automático: {entrega.estado}")

    async def _aguardar_confirmacao(self, entrada: DeliveryEntrada) -> None:
        while not self._confirmado:
            try:
                await workflow.wait_condition(
                    lambda: self._confirmado, timeout=timedelta(seconds=entrada.prazo_lembrete_s)
                )
            except TimeoutError:
                # No M1 o lembrete só é registrado; nada externo é enviado.
                self._lembretes += 1
                workflow.logger.info("lembrete de aprovação pendente: intent=%s", entrada.intent_id)
