"""Executor da etapa Plan do M1: sandbox efêmero, agente eco e destruição garantida."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from forja.application.portas.sandbox import EspecSandbox, Sandbox
from forja.infrastructure.agents.eco import AgenteEco
from forja.infrastructure.telemetry.otel import registrar_uso, span_sessao_agente
from forja.infrastructure.temporal.activities import EtapaEntrada, EtapaSaida


async def destruir_mesmo_cancelado(sandbox: Sandbox, sessao_id: str) -> None:
    """Se a activity for cancelada (/forja stop, pânico), o sandbox ainda é destruído."""
    tarefa = asyncio.ensure_future(sandbox.destruir(sessao_id))
    try:
        await asyncio.shield(tarefa)
    except asyncio.CancelledError:
        await tarefa
        raise


class ExecutorEco:
    def __init__(
        self, sandbox: Sandbox, agente: AgenteEco, resolver_repo: Callable[[str], str]
    ) -> None:
        self._sandbox = sandbox
        self._agente = agente
        self._resolver = resolver_repo

    async def __call__(self, entrada: EtapaEntrada) -> EtapaSaida:
        if entrada.etapa != "plan" or not entrada.repositorio:
            return EtapaSaida(etapa=entrada.etapa, resumo="noop")
        sessao = f"{entrada.intent_id}-eco"
        await self._sandbox.destruir(sessao)
        ativo = await self._sandbox.criar(EspecSandbox(sessao, self._resolver(entrada.repositorio)))
        try:
            with span_sessao_agente(entrada.intent_id, {"forja.etapa": entrada.etapa}) as span:
                resp = await self._agente.executar(ativo, f"{entrada.titulo}\n\n{entrada.corpo}")
                registrar_uso(span, resp.uso)
        finally:
            await destruir_mesmo_cancelado(self._sandbox, sessao)
        return EtapaSaida(etapa=entrada.etapa, resumo="eco", texto=resp.texto)
