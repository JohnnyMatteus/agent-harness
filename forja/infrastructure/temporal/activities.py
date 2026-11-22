"""Activities do DeliveryWorkflow: uma por etapa. Efeitos externos moram aqui."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from temporalio import activity
from temporalio.exceptions import ApplicationError

from forja.application.portas.publicador import Publicador
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


@dataclass(frozen=True)
class EtapaSaida:
    etapa: str
    resumo: str = ""
    texto: str = ""


@dataclass(frozen=True)
class PublicarEntrada:
    repositorio: str
    numero: int
    corpo: str
    chave: str


class ExecutorDeEtapa(Protocol):
    async def __call__(self, entrada: EtapaEntrada) -> EtapaSaida: ...


async def executor_noop(entrada: EtapaEntrada) -> EtapaSaida:
    return EtapaSaida(etapa=entrada.etapa, resumo="noop")


class DeliveryActivities:
    """Agrupa as activities com o executor, o publicador e as métricas injetados."""

    def __init__(
        self,
        executor: ExecutorDeEtapa = executor_noop,
        intervalo_heartbeat_s: float = 5.0,
        publicador: Publicador | None = None,
        metricas: MetricasForja | None = None,
    ) -> None:
        self._executor = executor
        self._intervalo = intervalo_heartbeat_s
        self._publicador = publicador
        self._metricas = metricas

    @activity.defn(name="publicar_comentario")
    async def publicar_comentario(self, entrada: PublicarEntrada) -> str:
        """Única escrita externa do fluxo; idempotente por `chave`."""
        if self._publicador is None:
            raise ApplicationError("publicador não configurado", non_retryable=True)
        return await self._publicador.comentar(
            entrada.repositorio, entrada.numero, entrada.corpo, entrada.chave
        )

    @activity.defn(name="registrar_desfecho")
    async def registrar_desfecho(self, desfecho: str) -> None:
        if self._metricas is None:
            return
        if desfecho == "concluida":
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
