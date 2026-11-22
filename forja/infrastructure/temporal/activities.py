"""Activities do DeliveryWorkflow: uma por etapa. Efeitos externos moram aqui."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Protocol

from temporalio import activity
from temporalio.exceptions import ApplicationError

from forja.application.portas.agente import UsoModelo
from forja.application.portas.harness import ContextoDaEntrega, Harness
from forja.application.portas.publicador import DestinoDaEntrega, PublicadorDeEntrega
from forja.infrastructure.github.cliente import nome_da_branch
from forja.infrastructure.telemetry.metricas import MetricasForja


@dataclass(frozen=True)
class EtapaEntrada:
    intent_id: str
    etapa: str
    # Contexto da origem. `titulo` e `corpo` são texto não confiável: só viram dado delimitado.
    repositorio: str = ""
    numero: int = 0
    titulo: str = ""
    corpo: str = ""
    url: str = ""
    # Artefatos já produzidos (intent.md, spec.md...), por nome; também dado, não instrução.
    artefatos: dict[str, str] = field(default_factory=dict[str, str])


@dataclass(frozen=True)
class EtapaSaida:
    etapa: str
    resumo: str = ""
    texto: str = ""
    pontos_em_aberto: int = 0
    tokens_entrada: int = 0
    tokens_saida: int = 0
    custo_usd: float = 0.0


@dataclass(frozen=True)
class PublicarEntrada:
    repositorio: str
    numero: int
    corpo: str
    chave: str


@dataclass(frozen=True)
class ArtefatoEntrada:
    repositorio: str
    intent_id: str
    slug: str
    nome: str
    conteudo: str = ""
    etapa: str = ""


@dataclass(frozen=True)
class HarnessEntrada:
    repositorio: str
    intent_id: str
    slug: str
    bloco: int = 0
    artefatos: dict[str, str] = field(default_factory=dict[str, str])
    feedback: str = ""


@dataclass(frozen=True)
class HarnessSaida:
    aprovadas: list[str] = field(default_factory=list[str])
    reprovadas: list[str] = field(default_factory=list[str])
    aprovado_pelo_avaliador: bool = False
    completa: bool = False
    verde: bool = False
    funcionalidades: int = 0
    feedback: str = ""
    violacoes: int = 0
    tokens_entrada: int = 0
    tokens_saida: int = 0
    custo_usd: float = 0.0


@dataclass(frozen=True)
class PrEntrada:
    repositorio: str
    intent_id: str
    slug: str
    titulo: str
    corpo: str


class ExecutorDeEtapa(Protocol):
    async def __call__(self, entrada: EtapaEntrada) -> EtapaSaida: ...


DESFECHOS_CONCLUIDOS = frozenset({"concluida", "artefatos_publicados", "verificada", "aprovada"})


class DeliveryActivities:
    """Agrupa as activities com o executor, o publicador e as métricas injetados."""

    def __init__(
        self,
        executor: ExecutorDeEtapa,
        intervalo_heartbeat_s: float = 5.0,
        publicador: PublicadorDeEntrega | None = None,
        metricas: MetricasForja | None = None,
        harness: Harness | None = None,
    ) -> None:
        self._harness_impl = harness
        self._executor = executor
        self._intervalo = intervalo_heartbeat_s
        self._publicador = publicador
        self._metricas = metricas

    def _medir(self, saida: EtapaSaida) -> None:
        self._medir_uso(UsoModelo(saida.tokens_entrada, saida.tokens_saida, saida.custo_usd))

    def _medir_uso(self, uso: UsoModelo) -> None:
        if self._metricas is not None:
            self._metricas.custo_usd.inc(uso.custo_usd)
            self._metricas.tokens.labels("entrada").inc(uso.tokens_entrada)
            self._metricas.tokens.labels("saida").inc(uso.tokens_saida)

    def _pub(self) -> PublicadorDeEntrega:
        if self._publicador is None:
            raise ApplicationError("publicador não configurado", non_retryable=True)
        return self._publicador

    @activity.defn(name="publicar_comentario")
    async def publicar_comentario(self, entrada: PublicarEntrada) -> str:
        """Escrita externa do fluxo; idempotente por `chave`."""
        return await self._pub().comentar(
            entrada.repositorio, entrada.numero, entrada.corpo, entrada.chave
        )

    @activity.defn(name="commitar_artefato")
    async def commitar_artefato(self, entrada: ArtefatoEntrada) -> str:
        info = activity.info()
        mensagem = (
            f"forja({entrada.etapa}): {entrada.nome}\n\n"
            f"Intent-Id: {entrada.intent_id}\nRun-Id: {info.workflow_run_id}\n"
            "Co-Authored-By: Forja <forja@users.noreply.github.com>"
        )
        destino = DestinoDaEntrega(entrada.repositorio, entrada.intent_id, entrada.slug)
        return await self._pub().commitar_artefato(
            destino, entrada.nome, entrada.conteudo, mensagem
        )

    @activity.defn(name="ler_artefato")
    async def ler_artefato(self, entrada: ArtefatoEntrada) -> str:
        """Versão da branch (um humano pode ter editado); vazio quando não há."""
        destino = DestinoDaEntrega(entrada.repositorio, entrada.intent_id, entrada.slug)
        return await self._pub().ler_artefato(destino, entrada.nome) or ""

    @activity.defn(name="abrir_pr")
    async def abrir_pr(self, entrada: PrEntrada) -> str:
        destino = DestinoDaEntrega(entrada.repositorio, entrada.intent_id, entrada.slug)
        return await self._pub().abrir_pr(destino, entrada.titulo, entrada.corpo)

    @activity.defn(name="registrar_desfecho")
    async def registrar_desfecho(self, desfecho: str) -> None:
        if self._metricas is None:
            return
        if desfecho in DESFECHOS_CONCLUIDOS:
            self._metricas.concluidas.inc()
        elif desfecho == "erro":
            self._metricas.com_erro.inc()

    async def _com_heartbeat[T](self, coro: Awaitable[T], detalhe: str) -> T:
        """O cancelamento só chega à activity pelo heartbeat; por isso o batimento roda enquanto
        o trabalho acontece, e o trabalho é cancelado junto."""
        trabalho = asyncio.ensure_future(coro)
        try:
            while True:
                activity.heartbeat(detalhe)
                feito, _ = await asyncio.wait({trabalho}, timeout=self._intervalo)
                if feito:
                    return trabalho.result()
        finally:
            if not trabalho.done():
                trabalho.cancel()
                await asyncio.gather(trabalho, return_exceptions=True)

    @activity.defn(name="executar_etapa")
    async def executar_etapa(self, entrada: EtapaEntrada) -> EtapaSaida:
        saida = await self._com_heartbeat(self._executor(entrada), entrada.etapa)
        self._medir(saida)
        return saida

    def _harness(self) -> Harness:
        if self._harness_impl is None:
            raise ApplicationError("harness não configurado", non_retryable=True)
        return self._harness_impl

    def _ctx(self, e: HarnessEntrada) -> ContextoDaEntrega:
        return ContextoDaEntrega(
            e.repositorio,
            e.intent_id,
            nome_da_branch(e.intent_id, e.slug),
            activity.info().workflow_run_id or "",
        )

    @activity.defn(name="harness_inicializar")
    async def harness_inicializar(self, e: HarnessEntrada) -> HarnessSaida:
        lista, uso = await self._com_heartbeat(
            self._harness().inicializar(
                self._ctx(e), e.artefatos["spec.md"], e.artefatos["plan.md"]
            ),
            "inicializar",
        )
        self._medir_uso(uso)
        return HarnessSaida(
            completa=lista.completa,
            funcionalidades=len(lista.features),
            tokens_entrada=uso.tokens_entrada,
            tokens_saida=uso.tokens_saida,
            custo_usd=uso.custo_usd,
        )

    @activity.defn(name="harness_bloco")
    async def harness_bloco(self, e: HarnessEntrada) -> HarnessSaida:
        r = await self._com_heartbeat(
            self._harness().executar_bloco(self._ctx(e), e.bloco, e.artefatos, e.feedback),
            f"bloco {e.bloco}",
        )
        self._medir_uso(r.uso)
        return HarnessSaida(
            aprovadas=list(r.aprovadas),
            reprovadas=list(r.reprovadas),
            aprovado_pelo_avaliador=r.aprovado_pelo_avaliador,
            completa=r.completa,
            feedback=r.feedback[:4000],
            violacoes=len(r.violacoes),
            tokens_entrada=r.uso.tokens_entrada,
            tokens_saida=r.uso.tokens_saida,
            custo_usd=r.uso.custo_usd,
        )

    @activity.defn(name="harness_verificar")
    async def harness_verificar(self, e: HarnessEntrada) -> HarnessSaida:
        v = await self._com_heartbeat(self._harness().verificar(self._ctx(e)), "verificar")
        return HarnessSaida(
            verde=v.verde,
            reprovadas=[f for f, ok in v.resultados.items() if not ok],
            aprovadas=[f for f, ok in v.resultados.items() if ok],
        )


# Referência para o workflow (nome estável da activity, sem importar a instância).
executar_etapa = DeliveryActivities.executar_etapa
