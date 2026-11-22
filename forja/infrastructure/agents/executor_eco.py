"""Executor da etapa Plan do M1: o agente eco, sem ferramenta, sobre o texto da issue."""

from __future__ import annotations

from forja.infrastructure.agents.eco import AgenteEco
from forja.infrastructure.telemetry.otel import registrar_uso, span_sessao_agente
from forja.infrastructure.temporal.activities import EtapaEntrada, EtapaSaida


class ExecutorEco:
    def __init__(self, agente: AgenteEco) -> None:
        self._agente = agente

    async def __call__(self, entrada: EtapaEntrada) -> EtapaSaida:
        if entrada.etapa != "plan" or not entrada.repositorio:
            return EtapaSaida(etapa=entrada.etapa, resumo="noop")
        with span_sessao_agente(entrada.intent_id, {"forja.etapa": entrada.etapa}) as span:
            resp = await self._agente.executar(f"{entrada.titulo}\n\n{entrada.corpo}")
            registrar_uso(span, resp.uso)
        return EtapaSaida(etapa=entrada.etapa, resumo="eco", texto=resp.texto)
