"""Activities do DeliveryWorkflow: uma por etapa. Efeitos externos moram aqui."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from temporalio import activity


@dataclass(frozen=True)
class EtapaEntrada:
    intent_id: str
    etapa: str


@dataclass(frozen=True)
class EtapaSaida:
    etapa: str
    resumo: str = ""


class ExecutorDeEtapa(Protocol):
    async def __call__(self, entrada: EtapaEntrada) -> EtapaSaida: ...


async def executor_noop(entrada: EtapaEntrada) -> EtapaSaida:
    return EtapaSaida(etapa=entrada.etapa, resumo="noop")


class DeliveryActivities:
    """Agrupa as activities com o executor injetado (o agente eco entra aqui no M1-12)."""

    def __init__(
        self, executor: ExecutorDeEtapa = executor_noop, intervalo_heartbeat_s: float = 5.0
    ) -> None:
        self._executor = executor
        self._intervalo = intervalo_heartbeat_s

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
