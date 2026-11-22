"""Raiz de composição: liga configuração, adaptadores e casos de uso. Só aqui se instancia."""

from __future__ import annotations

import httpx
from anthropic import AsyncAnthropic
from fastapi import FastAPI, Response
from pydantic import BaseModel
from redis.asyncio import Redis
from temporalio.client import Client
from temporalio.worker import Worker

from forja.application.casos_de_uso.acionar_panico import AcionarPanico
from forja.application.casos_de_uso.ativar_entrega import AtivarEntrega
from forja.application.casos_de_uso.harness import (
    ExecutarBloco,
    HarnessDaEntrega,
    InicializarHarness,
    VerificarEntrega,
)
from forja.application.casos_de_uso.memoria_do_repositorio import memorias_separadas
from forja.application.casos_de_uso.recuperar_conhecimento import RecuperarConhecimento
from forja.application.casos_de_uso.revisao import RevisarEntrega
from forja.application.portas.sdlc import PesquisaDeConhecimento
from forja.domain.revisao import REVISORES
from forja.infrastructure.agents.agent_sdk import AgentSdkRunner, ClienteSdk
from forja.infrastructure.agents.arquivos_git import ListadorGit
from forja.infrastructure.agents.avaliador import AvaliadorNaMessagesApi
from forja.infrastructure.agents.contexto import estrategia_do_modelo
from forja.infrastructure.agents.esquemas import (
    AchadosSaida,
    ContratoSaida,
    InicializacaoSaida,
    IntentSaida,
    PlanoSaida,
    RevisaoDeModeloSaida,
    SpecSaida,
)
from forja.infrastructure.agents.estruturado import AgenteEstruturado
from forja.infrastructure.agents.executor_sdlc import ExecutorSdlc
from forja.infrastructure.agents.harness_agentes import ExecutorAgente, InicializadorAgente
from forja.infrastructure.agents.pesquisa_rag import PesquisaRag, SemPesquisa
from forja.infrastructure.agents.revisores import RevisorDeModelo, foco_do_revisor
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
from forja.infrastructure.knowledge.configuracao import ConfiguracaoInvalida, embedder_do_ambiente
from forja.infrastructure.knowledge.postgres import IndicePostgres
from forja.infrastructure.persistencia.idempotencia_redis import IdempotenciaRedis
from forja.infrastructure.persistencia.memoria import ArmazemPostgres
from forja.infrastructure.sandbox.area_git import AreaGit
from forja.infrastructure.sandbox.docker import ConfigDocker, DockerSandbox
from forja.infrastructure.sandbox.remoto_git import RemotoGitHub
from forja.infrastructure.sandbox.repositorios import RepositoriosLocais
from forja.infrastructure.sandbox.worktree import GerenciadorWorktree
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


def _github(cfg: GitHubConfig) -> tuple[GitHubCliente, GitHubAppAuth, httpx.AsyncClient]:
    http = httpx.AsyncClient(base_url=cfg.api_url, timeout=15.0)
    auth = GitHubAppAuth(cfg.app_id, carregar_chave_privada(), http)
    return GitHubCliente(auth, http), auth, http


def montar_gateway(
    ajustes: Ajustes, client: Client, redis: Redis, metricas: MetricasForja
) -> FastAPI:
    cfg = GitHubConfig()  # type: ignore[call-arg]  # segredo vem do ambiente
    github, _, _ = _github(cfg)
    entregas = TemporalEntregaGateway(
        client, harness=ajustes.harness, automerge=frozenset(ajustes.automerge_repos)
    )
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


def montar_harness(
    ajustes: Ajustes, github: GitHubCliente, auth: GitHubAppAuth, metricas: MetricasForja
) -> HarnessDaEntrega:
    """Build de longa duração. Sem condição de segurança atendida, falha em vez de improvisar."""
    if not ajustes.publicar:
        raise ConfiguracaoInvalida(
            "FORJA_HARNESS exige FORJA_PUBLICAR=true: a continuidade vive na branch remota"
        )
    if not ajustes.harness_aceita_chave_no_sandbox:
        raise ConfiguracaoInvalida(
            "FORJA_HARNESS_ACEITA_CHAVE_NO_SANDBOX=true é obrigatório: a ANTHROPIC_API_KEY chega "
            "ao CLI do agente, no mesmo container e uid do código do repositório, e um teste "
            "consegue lê-la (ADR 0040). Use chave com limite de gasto e sem outros acessos."
        )
    if not ajustes.database_url:
        raise ConfiguracaoInvalida("FORJA_HARNESS exige DATABASE_URL (memória por repositório)")
    if not ajustes.modelo_avaliador:
        raise ConfiguracaoInvalida(
            "FORJA_MODELO_AVALIADOR não definido: a escolha do modelo é do autor"
        )
    if not ajustes.preco_avaliador_entrada or not ajustes.preco_avaliador_saida:
        raise ConfiguracaoInvalida(
            "FORJA_PRECO_AVALIADOR_ENTRADA e FORJA_PRECO_AVALIADOR_SAIDA (USD por milhão de "
            "tokens) são obrigatórios: sem preço o custo do Avaliador seria 0"
        )
    armazem = ArmazemPostgres(ajustes.database_url)
    armazem.garantir_esquema()
    memoria_executor, memoria_avaliador = memorias_separadas(armazem)

    sandbox = DockerSandbox(
        GerenciadorWorktree(ajustes.worktrees_dir.resolve()),
        cfg=ConfigDocker(imagem=ajustes.imagem_agente),
    )
    repos = RepositoriosLocais(ajustes.repos_dir)
    area = AreaGit()
    remoto = RemotoGitHub(auth, dry_run=False)

    def runner(prompt: str) -> AgentSdkRunner:
        return AgentSdkRunner(carregar_prompt(prompt), modelo=ajustes.modelo)

    executor = ExecutorAgente(
        runner("executor"),
        AgenteEstruturado(runner("contratante"), ContratoSaida, "contrato"),
        memoria_executor,
        ajustes.modelo,
        ao_bloquear=lambda ferramenta, _: metricas.bloqueios.labels(ferramenta).inc(),
    )
    avaliador = AvaliadorNaMessagesApi(
        AsyncAnthropic(),
        ajustes.modelo_avaliador,
        memoria_avaliador,
        estrategia_do_modelo(ajustes.modelo_avaliador),
        preco_por_milhao=(ajustes.preco_avaliador_entrada, ajustes.preco_avaliador_saida),
    )
    inicializador = InicializadorAgente(
        AgenteEstruturado(runner("inicializador"), InicializacaoSaida, "inicializador")
    )
    return HarnessDaEntrega(
        InicializarHarness(sandbox, area, remoto, repos.caminho, inicializador),
        ExecutarBloco(
            sandbox,
            area,
            remoto,
            repos.caminho,
            executor,
            avaliador,
            ajustes.tamanho_do_bloco,
            lambda _: metricas.bloqueios.labels("auditoria").inc(),
        ),
        VerificarEntrega(sandbox, area, remoto, repos.caminho),
    )


def montar_revisao(
    ajustes: Ajustes, github: GitHubCliente, cliente: ClienteSdk | None = None
) -> RevisarEntrega:
    """Quatro revisores independentes e sem ferramenta; o diff chega por código (ADR 0037)."""
    revisores = [
        RevisorDeModelo(
            nome,
            AgenteEstruturado(
                AgentSdkRunner(
                    carregar_prompt("revisor") + foco_do_revisor(nome), cliente, ajustes.modelo
                )
                if cliente
                else AgentSdkRunner(
                    carregar_prompt("revisor") + foco_do_revisor(nome), modelo=ajustes.modelo
                ),
                RevisaoDeModeloSaida,
                f"revisor-{nome}",
            ),
        )
        for nome in REVISORES
    ]
    return RevisarEntrega(revisores, github)


def montar_worker(
    ajustes: Ajustes, client: Client, redis: Redis, metricas: MetricasForja
) -> Worker:
    cfg = GitHubConfig()  # type: ignore[call-arg]
    github, auth, _ = _github(cfg)
    publicador = PublicadorGitHub(
        github, IdempotenciaRedis(redis), dry_run=not ajustes.publicar, revisao=github
    )
    harness = montar_harness(ajustes, github, auth, metricas) if ajustes.harness else None
    atividades = DeliveryActivities(
        montar_executor(ajustes),
        publicador=publicador,
        metricas=metricas,
        harness=harness,
        revisor=montar_revisao(ajustes, github) if harness else None,
        leitura=github,
        escrita=publicador,
    )
    return criar_worker(client, atividades)
