"""DeliveryWorkflow: um workflow por intenção, com portões humanos por sinal.

Código de workflow precisa ser determinístico; todo efeito externo fica em activities.
As transições vêm do agregado `Entrega` do domínio; o workflow só as dispara.

M3 (até o PR): Plan (Intérprete) -> confirmação -> Design (Spec) -> portão de spec, se houver
pontos em aberto -> Build (Planner) -> PR de artefatos em rascunho. Verificação, Executor e
Avaliador são o M4; a rejeição termina o workflow sem aresta nova na máquina de estados.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from forja.domain.entrega import Entrega
    from forja.domain.estados import Estado
    from forja.infrastructure.temporal.activities import (
        ArtefatoEntrada,
        EtapaEntrada,
        EtapaSaida,
        PrEntrada,
        PublicarEntrada,
    )

# Erros que repetir não resolve: saída de modelo fora do schema, dado inválido, branch recusada.
NAO_REPETIR = ["SaidaInvalida", "ArtefatoInvalido", "ValueError", "BranchProtegida", "SandboxError"]
LIMITE_MOTIVO = 500


class Desfecho(StrEnum):
    CONCLUIDA = "concluida"
    CANCELADA = "cancelada"
    REJEITADA = "rejeitada"
    ARTEFATOS_PUBLICADOS = "artefatos_publicados"


@dataclass(frozen=True)
class DeliveryEntrada:
    intent_id: str
    # Prazo do lembrete de decisão (configuração; o design doc cita 48 h como exemplo).
    prazo_lembrete_s: float = 48 * 3600
    timeout_etapa_s: float = 3600
    heartbeat_s: float = 30
    # Origem da intenção. Titulo e corpo são texto não confiável (dado, nunca instrução).
    repositorio: str = ""
    numero: int = 0
    titulo: str = ""
    corpo: str = ""
    url: str = ""
    slug: str = "intent"
    # Quem pediu (logins em minúsculas): só eles confirmam o intent. Vazio não restringe.
    solicitantes: list[str] = field(default_factory=list[str])


@dataclass
class DeliverySaida:
    intent_id: str
    desfecho: Desfecho
    etapa_final: str
    etapas_executadas: list[str] = field(default_factory=list[str])
    lembretes: int = 0
    sinais_repetidos: int = 0
    pr_url: str = ""
    motivo_da_rejeicao: str = ""
    custo_usd: float = 0.0


def workflow_id(intent_id: str) -> str:
    """Id determinístico: o próprio intent_id (ADR 0030), um workflow por intenção."""
    return intent_id


@workflow.defn(name="DeliveryWorkflow")
class DeliveryWorkflow:
    def __init__(self) -> None:
        self._entrega: Entrega | None = None
        self._parar = False
        self._lembretes = 0
        self._repetidos = 0
        self._executadas: list[str] = []
        self._artefatos: dict[str, str] = {}
        self._portao: str | None = None
        self._decisao: tuple[str, str, str] | None = None
        self._pr_url = ""
        self._motivo = ""
        self._solicitantes: frozenset[str] = frozenset()
        self._custo = 0.0

    @workflow.signal
    def confirmar(self, quem: str = "") -> None:
        """Só vale no portão do intent, de quem pediu. Confirmação antecipada (antes de o resumo
        existir) é descartada: ninguém confirma o que ainda não viu."""
        if self._portao == "intent" and self._decisao is None and self._pediu(quem):
            self._decisao = ("aprovada", quem, "")
        else:
            workflow.logger.info("confirmação descartada (sem portão aberto ou não solicitante)")

    @workflow.signal
    def aprovar(self, quem: str = "") -> None:
        """Só vale num portão de decisão aberto: aprovação antecipada é descartada."""
        if self._portao not in (None, "intent") and self._decisao is None:
            self._decisao = ("aprovada", quem, "")

    @workflow.signal
    def rejeitar(self, quem: str = "", motivo: str = "") -> None:
        if self._portao is not None and self._decisao is None:
            self._decisao = ("rejeitada", quem, motivo[:LIMITE_MOTIVO])

    def _pediu(self, quem: str) -> bool:
        return not self._solicitantes or quem.lower() in self._solicitantes

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
    def portao_aberto(self) -> str:
        return self._portao or ""

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
                    desfecho = corpo.result()
                except BaseException:
                    await self._registrar_desfecho("erro")
                    raise
                await self._registrar_desfecho(desfecho.value)
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
            pr_url=self._pr_url,
            motivo_da_rejeicao=self._motivo,
            custo_usd=self._custo,
        )

    async def _percorrer(self, entrada: DeliveryEntrada) -> Desfecho:
        entrega = self._entrega = Entrega(intent_id=entrada.intent_id)
        self._solicitantes = frozenset(s.lower() for s in entrada.solicitantes)

        plan = await self._executar(entrada, "plan")  # Intérprete
        self._artefatos["intent.md"] = plan.texto
        await self._commitar(entrada, "intent.md", "plan")
        self._abrir_portao("intent")
        await self._comentar(
            entrada,
            "intent",
            "Resumo da intenção. Quem pediu responde `/forja confirm` para seguir (pode editar "
            f"`intent.md` na branch antes: a versão confirmada é a que vale).\n\n{plan.texto}",
        )
        decisao, quem, motivo = await self._esperar_decisao(entrada, "confirmação do intent")
        if decisao == "rejeitada":
            return await self._encerrar_rejeitado(entrada, "intent", quem, motivo)
        editado = await self._ler(entrada, "intent.md")
        if editado:
            self._artefatos["intent.md"] = editado
        entrega.confirmar_intent()

        design = await self._executar(entrada, "design")  # Spec
        self._artefatos["spec.md"] = design.texto
        await self._commitar(entrada, "spec.md", "design")
        entrega.concluir_spec(design.pontos_em_aberto)
        if entrega.estado is Estado.AGUARDANDO_SPEC:
            self._abrir_portao("spec")
            await self._comentar(
                entrada,
                "spec",
                f"A spec tem {design.pontos_em_aberto} ponto(s) em aberto. Edite `spec.md` na "
                "branch se precisar e responda `/forja approve` ou `/forja reject <motivo>`."
                f"\n\n{design.texto}",
            )
            decisao, quem, motivo = await self._esperar_decisao(entrada, "decisão do portão spec")
            if decisao == "rejeitada":
                return await self._encerrar_rejeitado(entrada, "spec", quem, motivo)
            editada = await self._ler(entrada, "spec.md")
            if editada:
                self._artefatos["spec.md"] = editada
            entrega.resolver_pontos_em_aberto()

        build = await self._executar(entrada, "build")  # Planner
        self._artefatos["plan.md"] = build.texto
        await self._commitar(entrada, "plan.md", "build")
        self._pr_url = await self._abrir_pr(entrada)
        await self._comentar(entrada, "pr", f"PR de artefatos aberto em rascunho: {self._pr_url}")
        return Desfecho.ARTEFATOS_PUBLICADOS

    # --- portões -----------------------------------------------------------------------

    def _abrir_portao(self, nome: str) -> None:
        """Abre o portão antes de avisar o humano: nenhuma resposta chega antes dele."""
        self._portao, self._decisao = nome, None

    async def _esperar_decisao(self, entrada: DeliveryEntrada, o_que: str) -> tuple[str, str, str]:
        await self._aguardar(lambda: self._decisao is not None, entrada, o_que)
        decisao = self._decisao or ("rejeitada", "", "")
        self._portao = None
        return decisao

    async def _encerrar_rejeitado(
        self, entrada: DeliveryEntrada, onde: str, quem: str, motivo: str
    ) -> Desfecho:
        self._motivo = motivo
        await self._comentar(
            entrada, f"{onde}-rejeitada", f"Entrega encerrada: {onde} rejeitada por {quem}."
        )
        return Desfecho.REJEITADA

    async def _aguardar(
        self, condicao: Callable[[], bool], entrada: DeliveryEntrada, o_que: str
    ) -> None:
        while not condicao():
            try:
                await workflow.wait_condition(
                    condicao, timeout=timedelta(seconds=entrada.prazo_lembrete_s)
                )
            except TimeoutError:
                self._lembretes += 1
                workflow.logger.info("lembrete pendente: intent=%s %s", entrada.intent_id, o_que)
                await self._comentar(
                    entrada, f"lembrete-{self._lembretes}", f"Lembrete: aguardando {o_que}."
                )

    # --- activities --------------------------------------------------------------------

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
                url=entrada.url,
                artefatos=dict(self._artefatos),
            ),
            result_type=EtapaSaida,
            start_to_close_timeout=timedelta(seconds=entrada.timeout_etapa_s),
            heartbeat_timeout=timedelta(seconds=entrada.heartbeat_s),
            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            retry_policy=RetryPolicy(maximum_attempts=3, non_retryable_error_types=NAO_REPETIR),
        )
        self._executadas.append(saida.etapa)
        self._custo += saida.custo_usd
        return saida

    def _artefato(
        self, e: DeliveryEntrada, nome: str, conteudo: str = "", etapa: str = ""
    ) -> ArtefatoEntrada:
        return ArtefatoEntrada(e.repositorio, e.intent_id, e.slug, nome, conteudo, etapa)

    async def _commitar(self, entrada: DeliveryEntrada, nome: str, etapa: str) -> None:
        """Só o workflow escreve no GitHub (ADR 0007); o commit é idempotente."""
        if not entrada.repositorio:
            return
        await workflow.execute_activity(
            "commitar_artefato",
            self._artefato(entrada, nome, self._artefatos[nome], etapa),
            result_type=str,
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=RetryPolicy(maximum_attempts=5, non_retryable_error_types=NAO_REPETIR),
        )

    async def _ler(self, entrada: DeliveryEntrada, nome: str) -> str:
        if not entrada.repositorio:
            return ""
        return await workflow.execute_activity(
            "ler_artefato",
            self._artefato(entrada, nome),
            result_type=str,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=5, non_retryable_error_types=NAO_REPETIR),
        )

    async def _abrir_pr(self, entrada: DeliveryEntrada) -> str:
        if not entrada.repositorio:
            return ""
        corpo = (
            f"Entrega da intent `{entrada.intent_id}` (issue #{entrada.numero}). "
            f"Artefatos em `.forja/{entrada.intent_id}/`. Em rascunho: o código ainda não foi "
            "implementado.\n\n"
            + "\n\n".join(self._artefatos[n] for n in ("intent.md", "spec.md", "plan.md"))
        )
        return await workflow.execute_activity(
            "abrir_pr",
            PrEntrada(
                entrada.repositorio,
                entrada.intent_id,
                entrada.slug,
                f"forja: {entrada.titulo}",
                corpo,
            ),
            result_type=str,
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=RetryPolicy(maximum_attempts=5, non_retryable_error_types=NAO_REPETIR),
        )

    async def _comentar(self, entrada: DeliveryEntrada, chave: str, corpo: str) -> None:
        if not entrada.repositorio:
            return
        await workflow.execute_activity(
            "publicar_comentario",
            PublicarEntrada(
                entrada.repositorio, entrada.numero, corpo, f"{entrada.intent_id}:{chave}"
            ),
            result_type=str,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=5, non_retryable_error_types=NAO_REPETIR),
        )

    async def _registrar_desfecho(self, desfecho: str) -> None:
        await workflow.execute_activity(
            "registrar_desfecho",
            desfecho,
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
