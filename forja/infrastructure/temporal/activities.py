"""Activities do DeliveryWorkflow: uma por etapa. Efeitos externos moram aqui."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol

from temporalio import activity
from temporalio.exceptions import ApplicationError

from forja.application.portas.publicador import DestinoDaEntrega, PublicadorDeEntrega
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
class PrEntrada:
    repositorio: str
    intent_id: str
    slug: str
    titulo: str
    corpo: str


class ExecutorDeEtapa(Protocol):
    async def __call__(self, entrada: EtapaEntrada) -> EtapaSaida: ...


DESFECHOS_CONCLUIDOS = frozenset({"concluida", "artefatos_publicados", "pr_aberto", "aprovada"})


class DeliveryActivities:
    """Agrupa as activities com o executor, o publicador e as métricas injetados."""

    def __init__(
        self,
        executor: ExecutorDeEtapa,
        intervalo_heartbeat_s: float = 5.0,
        publicador: PublicadorDeEntrega | None = None,
        metricas: MetricasForja | None = None,
    ) -> None:
        self._executor = executor
        self._intervalo = intervalo_heartbeat_s
        self._publicador = publicador
        self._metricas = metricas

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

    @activity.defn(name="executar_etapa")
    async def executar_etapa(self, entrada: EtapaEntrada) -> EtapaSaida:
        # O cancelamento só chega à activity pelo heartbeat; por isso o batimento roda
        # enquanto o executor trabalha, e o executor é cancelado junto.
        trabalho = asyncio.ensure_future(self._executor(entrada))
        try:
            while True:
                activity.heartbeat(entrada.etapa)
                feito, _ = await asyncio.wait({trabalho}, timeout=self._intervalo)
                if feito:
                    return trabalho.result()
        finally:
            if not trabalho.done():
                trabalho.cancel()
                await asyncio.gather(trabalho, return_exceptions=True)


# Referência para o workflow (nome estável da activity, sem importar a instância).
executar_etapa = DeliveryActivities.executar_etapa
