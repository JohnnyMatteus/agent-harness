"""Raiz de composição: liga configuração, adaptadores e casos de uso. Só aqui se instancia."""

from __future__ import annotations

import httpx
from fastapi import FastAPI, Response
from redis.asyncio import Redis
from temporalio.client import Client
from temporalio.worker import Worker

from forja.application.casos_de_uso.acionar_panico import AcionarPanico
from forja.application.casos_de_uso.ativar_entrega import AtivarEntrega
from forja.infrastructure.agents.eco import AgenteEco
from forja.infrastructure.agents.executor_eco import ExecutorEco
from forja.infrastructure.github.app_auth import GitHubAppAuth
from forja.infrastructure.github.chave_privada import carregar_chave_privada
from forja.infrastructure.github.cliente import GitHubCliente
from forja.infrastructure.github.config import GitHubConfig
from forja.infrastructure.github.entregas_vistas import RegistroEntregasRedis
from forja.infrastructure.github.publicador import PublicadorGitHub
from forja.infrastructure.persistencia.idempotencia_redis import IdempotenciaRedis
from forja.infrastructure.telemetry.metricas import CONTENT_TYPE, MetricasForja
from forja.infrastructure.telemetry.otel import configurar_tracing, interceptor_temporal
from forja.infrastructure.temporal.activities import DeliveryActivities
from forja.infrastructure.temporal.worker import TemporalEntregaGateway, criar_worker
from forja.interfaces.cli.ajustes import Ajustes
from forja.interfaces.http.app import criar_app
from forja.interfaces.http.panico import DependenciasPanico
from forja.interfaces.http.webhooks import ConfigWebhook, DependenciasWebhook


async def conectar_temporal(ajustes: Ajustes) -> Client:
    configurar_tracing(ajustes.otlp_endpoint)
    return await Client.connect(
        ajustes.temporal_address,
        namespace=ajustes.temporal_namespace,
        interceptors=[interceptor_temporal()],
    )


def _github(cfg: GitHubConfig) -> tuple[GitHubCliente, httpx.AsyncClient]:
    http = httpx.AsyncClient(base_url=cfg.api_url, timeout=15.0)
    auth = GitHubAppAuth(cfg.app_id, carregar_chave_privada(), http)
    return GitHubCliente(auth, http), http


def montar_gateway(
    ajustes: Ajustes, client: Client, redis: Redis, metricas: MetricasForja
) -> FastAPI:
    cfg = GitHubConfig()  # type: ignore[call-arg]  # segredo vem do ambiente
    github, _ = _github(cfg)
    entregas = TemporalEntregaGateway(client)
    ativar = AtivarEntrega(entregas, github, frozenset(ajustes.repos_habilitados))
    app = criar_app(
        DependenciasWebhook(
            ConfigWebhook(cfg.webhook_secret.get_secret_value(), cfg.max_corpo_bytes),
            RegistroEntregasRedis(redis),
            ativar,
            metricas,
        ),
        DependenciasPanico(ajustes.panico_token_sha256, AcionarPanico(entregas)),
    )

    @app.get("/metrics")
    async def metricas_endpoint() -> Response:  # pyright: ignore[reportUnusedFunction]
        return Response(metricas.exportar(), media_type=CONTENT_TYPE)

    return app


def montar_worker(
    ajustes: Ajustes, client: Client, redis: Redis, metricas: MetricasForja
) -> Worker:
    cfg = GitHubConfig()  # type: ignore[call-arg]
    github, _ = _github(cfg)
    eco = AgenteEco.com_sdk()
    publicador = PublicadorGitHub(github, IdempotenciaRedis(redis), dry_run=not ajustes.publicar)
    atividades = DeliveryActivities(ExecutorEco(eco), publicador=publicador, metricas=metricas)
    return criar_worker(client, atividades)
