"""Binário `forja`: `serve` (gateway HTTP), `worker` (activities e workflows) e `monitor`
(inicia o monitor de bandas, M6)."""

from __future__ import annotations

import argparse
import asyncio
import logging

import uvicorn
from prometheus_client import start_http_server
from redis.asyncio import Redis

from forja.infrastructure.telemetry.metricas import MetricasForja
from forja.infrastructure.temporal.worker import iniciar_monitores
from forja.interfaces.cli.ajustes import Ajustes
from forja.interfaces.cli.composicao import conectar_temporal, montar_gateway, montar_worker


async def servir(ajustes: Ajustes) -> None:
    client = await conectar_temporal(ajustes)
    redis = Redis.from_url(ajustes.redis_url)  # pyright: ignore[reportUnknownMemberType]
    app = montar_gateway(ajustes, client, redis, MetricasForja())
    config = uvicorn.Config(app, host=ajustes.api_host, port=ajustes.api_porta, log_level="info")
    await uvicorn.Server(config).serve()


async def trabalhar(ajustes: Ajustes) -> None:
    client = await conectar_temporal(ajustes)
    redis = Redis.from_url(ajustes.redis_url)  # pyright: ignore[reportUnknownMemberType]
    metricas = MetricasForja()
    start_http_server(ajustes.metricas_porta, registry=metricas.registry)
    await montar_worker(ajustes, client, redis, metricas).run()


async def monitorar(ajustes: Ajustes) -> None:
    """Inicia (idempotente) o monitor de bandas de cada repo em FORJA_MONITOR_REPOS."""
    if not ajustes.monitor_repos:
        raise SystemExit("FORJA_MONITOR_REPOS vazio: o monitor está desligado")
    client = await conectar_temporal(ajustes)
    ids = await iniciar_monitores(client, ajustes.monitor_repos, ajustes.monitor_intervalo_s)
    print("monitores ativos:", ", ".join(ids))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="forja")
    parser.add_argument("comando", choices=["serve", "worker", "monitor"])
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    ajustes = Ajustes.do_ambiente()
    acao = {"serve": servir, "worker": trabalhar, "monitor": monitorar}[args.comando]
    asyncio.run(acao(ajustes))


if __name__ == "__main__":
    main()
