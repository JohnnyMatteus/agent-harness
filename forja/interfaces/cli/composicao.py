"""Raiz de composição: liga configuração, adaptadores e casos de uso. Só aqui se instancia."""

from __future__ import annotations

import httpx
from fastapi import FastAPI, Response
from pydantic import BaseModel
from redis.asyncio import Redis
from temporalio.client import Client
from temporalio.worker import Worker

from forja.application.casos_de_uso.acionar_panico import AcionarPanico
from forja.application.casos_de_uso.ativar_entrega import AtivarEntrega
from forja.application.casos_de_uso.recuperar_conhecimento import RecuperarConhecimento
from forja.application.portas.sdlc import PesquisaDeConhecimento
from forja.infrastructure.agents.agent_sdk import AgentSdkRunner, ClienteSdk
from forja.infrastructure.agents.arquivos_git import ListadorGit
from forja.infrastructure.agents.esquemas import AchadosSaida, IntentSaida, PlanoSaida, SpecSaida
from forja.infrastructure.agents.estruturado import AgenteEstruturado
from forja.infrastructure.agents.executor_sdlc import ExecutorSdlc
from forja.infrastructure.agents.pesquisa_rag import PesquisaRag, SemPesquisa
from forja.infrastructure.agents.sdlc import (
    EspecificadorMultiagente,
    InterpreteAgente,
    PlanejadorAgente,
    carregar_prompt,
)
from forja.infrastructure.github.app_auth import GitHubAppAuth
from forja.infrastructure.github.chave_privada import carregar_chave_privada
from forja.infrastructure.github.cliente import GitHubCliente
from forja.infrastructure.github.config import GitHubConfig
from forja.infrastructure.github.entregas_vistas import RegistroEntregasRedis
from forja.infrastructure.github.publicador import PublicadorGitHub
from forja.infrastructure.knowledge.configuracao import embedder_do_ambiente
from forja.infrastructure.knowledge.postgres import IndicePostgres
from forja.infrastructure.persistencia.idempotencia_redis import IdempotenciaRedis
from forja.infrastructure.sandbox.repositorios import RepositoriosLocais
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


def montar_pesquisa(ajustes: Ajustes) -> PesquisaDeConhecimento:
    """RAG do M2 por código (nunca pelo MCP do agente); sem banco ou embedder, sem fontes."""
    if not ajustes.database_url or not ajustes.embedder:
        return SemPesquisa()
    embedder = embedder_do_ambiente({"FORJA_EMBEDDER": ajustes.embedder})
    return PesquisaRag(RecuperarConhecimento(IndicePostgres(ajustes.database_url), embedder))


def montar_executor(
    ajustes: Ajustes,
    pesquisa: PesquisaDeConhecimento | None = None,
    cliente: ClienteSdk | None = None,
) -> ExecutorSdlc:
    """Agentes do SDLC, todos sem ferramenta (ADR 0036). `cliente` é o ponto de injeção do SDK."""

    def agente[S: BaseModel](prompt: str, schema: type[S]) -> AgenteEstruturado[S]:
        runner = (
            AgentSdkRunner(carregar_prompt(prompt), cliente, ajustes.modelo)
            if cliente
            else AgentSdkRunner(carregar_prompt(prompt), modelo=ajustes.modelo)
        )
        return AgenteEstruturado(runner, schema, prompt)

    especificador = EspecificadorMultiagente(
        pesquisa or montar_pesquisa(ajustes),
        agente("pesquisador", AchadosSaida),
        agente("spec", SpecSaida),
    )
    planejador = PlanejadorAgente(
        agente("planner", PlanoSaida), ListadorGit(RepositoriosLocais(ajustes.repos_dir))
    )
    return ExecutorSdlc(
        InterpreteAgente(agente("interprete", IntentSaida)), especificador, planejador
    )


def montar_worker(
    ajustes: Ajustes, client: Client, redis: Redis, metricas: MetricasForja
) -> Worker:
    cfg = GitHubConfig()  # type: ignore[call-arg]
    github, _ = _github(cfg)
    publicador = PublicadorGitHub(github, IdempotenciaRedis(redis), dry_run=not ajustes.publicar)
    atividades = DeliveryActivities(
        montar_executor(ajustes), publicador=publicador, metricas=metricas
    )
    return criar_worker(client, atividades)
