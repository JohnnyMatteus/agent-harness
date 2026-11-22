"""M1 ponta a ponta: webhook assinado -> gateway -> Temporal -> sandbox -> eco -> comentário.

Roda com sandbox em memória em todo `pytest`; a variante `docker` usa o `DockerSandbox` real e
só roda no CI (`pytest -m integration`, depois de `infra/sandbox/preparar.sh`).
O GitHub é falso e local; o SDK do agente é falso.
"""

# pyright: basic
from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
import subprocess
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fakeredis
import httpx
import pytest
import pytest_asyncio
from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from temporalio.testing import WorkflowEnvironment

from forja.application.casos_de_uso.acionar_panico import AcionarPanico
from forja.application.casos_de_uso.ativar_entrega import AtivarEntrega
from forja.application.portas.sandbox import EspecSandbox, ResultadoComando
from forja.domain.intent import Origem, TipoDeOrigem, intent_id_de
from forja.infrastructure.agents.eco import AgenteEco
from forja.infrastructure.agents.executor_eco import ExecutorEco
from forja.infrastructure.github.app_auth import GitHubAppAuth
from forja.infrastructure.github.assinatura import assinar
from forja.infrastructure.github.cliente import GitHubCliente
from forja.infrastructure.github.entregas_vistas import RegistroEntregasRedis
from forja.infrastructure.github.publicador import PublicadorGitHub
from forja.infrastructure.persistencia.idempotencia_redis import IdempotenciaRedis
from forja.infrastructure.sandbox.docker import DockerSandbox
from forja.infrastructure.sandbox.repositorios import RepositoriosLocais
from forja.infrastructure.sandbox.worktree import GerenciadorWorktree
from forja.infrastructure.telemetry.metricas import MetricasForja
from forja.infrastructure.temporal.activities import DeliveryActivities
from forja.infrastructure.temporal.worker import TemporalEntregaGateway, criar_worker
from forja.interfaces.http.app import criar_app
from forja.interfaces.http.panico import DependenciasPanico
from forja.interfaces.http.webhooks import ConfigWebhook, DependenciasWebhook
from tests.integracao.github_falso import GitHubFalso

pytestmark = pytest.mark.asyncio(loop_scope="module")

SEGREDO = "segredo-do-webhook"
FIXTURES = Path(__file__).parents[1] / "fixtures" / "github"
REPO = "acme-demo/loja-exemplo"
ID_ISSUE_42 = intent_id_de(Origem(TipoDeOrigem.ISSUE_GITHUB, REPO, "42", "t"))


class SandboxEmMemoria:
    def __init__(self, raiz: Path) -> None:
        self.raiz = raiz
        self.criados: list[str] = []
        self.destruidos: list[str] = []

    async def criar(self, spec: EspecSandbox) -> Any:
        self.criados.append(spec.sessao_id)
        wt = self.raiz / spec.sessao_id
        wt.mkdir(parents=True, exist_ok=True)
        sessao = spec.sessao_id

        class Ativo:
            sessao_id = sessao
            worktree = wt

            async def executar(self, comando: list[str], timeout_s: float = 60.0):
                return ResultadoComando(0, "", "")

        return Ativo()

    async def destruir(self, sessao_id: str) -> None:
        self.destruidos.append(sessao_id)


class SdkFalso:
    def __init__(self) -> None:
        self.atraso = 0.0
        self.chamadas: list[tuple[str, ClaudeAgentOptions]] = []

    async def __call__(self, *, prompt: str, options: ClaudeAgentOptions):
        self.chamadas.append((prompt, options))
        await asyncio.sleep(self.atraso)
        yield AssistantMessage(content=[TextBlock(text="x")], model="m")
        yield ResultMessage(
            subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
            session_id="s", total_cost_usd=0.01,
            usage={"input_tokens": 10, "output_tokens": 5}, result="eco: corrigir login",
        )  # fmt: skip


@dataclass
class Ambiente:
    http: httpx.AsyncClient
    github: GitHubFalso
    sdk: SdkFalso
    sandbox: Any
    spans: InMemorySpanExporter
    metricas: MetricasForja
    entregas: dict[str, int] = field(default_factory=dict)

    async def webhook(self, nome: str, entrega: str) -> dict[str, str]:
        corpo = (FIXTURES / f"{nome}.json").read_bytes()
        evento = "issue_comment" if nome.startswith("issue_comment") else "issues"
        r = await self.http.post(
            "/webhooks/github",
            content=corpo,
            headers={
                "X-Hub-Signature-256": assinar(SEGREDO, corpo),
                "X-GitHub-Event": evento,
                "X-GitHub-Delivery": entrega,
                "Content-Type": "application/json",
            },
        )
        assert r.status_code == 202, r.text
        return r.json()


async def esperar(condicao: Callable[[], bool], segundos: float = 30) -> None:
    async with asyncio.timeout(segundos):
        while not condicao():
            await asyncio.sleep(0.05)


GIT_IDENTIDADE = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]


def _repo_git(raiz: Path) -> None:
    destino = raiz / REPO
    destino.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=destino, check=True)
    subprocess.run(
        [*GIT_IDENTIDADE, "commit", "-q", "--allow-empty", "-m", "i"],
        cwd=destino,
        check=True,
    )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def temporal():
    async with await WorkflowEnvironment.start_time_skipping() as e:
        yield e


@pytest.fixture(
    params=["memoria", pytest.param("docker", marks=pytest.mark.integration)], scope="module"
)
def variante(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest_asyncio.fixture(loop_scope="module")
async def amb(
    temporal: WorkflowEnvironment, variante: str, tmp_path: Path, chave_pem: str, monkeypatch
) -> AsyncIterator[Ambiente]:
    if variante == "docker" and shutil.which("docker") is None:
        pytest.skip("sem Docker")
    exp = InMemorySpanExporter()
    prov = TracerProvider()
    prov.add_span_processor(SimpleSpanProcessor(exp))
    monkeypatch.setattr(
        "forja.infrastructure.telemetry.otel.trace.get_tracer",
        lambda n, *a, **k: prov.get_tracer(n),
    )
    from temporalio.contrib.opentelemetry import TracingInterceptor

    client = temporal.client.__class__(
        temporal.client.service_client,
        namespace=temporal.client.namespace,
        interceptors=[TracingInterceptor(prov.get_tracer("forja"))],
    )
    _repo_git(tmp_path / "repos")
    if variante == "docker":
        sandbox: Any = DockerSandbox(GerenciadorWorktree(tmp_path / "wt"))
    else:
        sandbox = SandboxEmMemoria(tmp_path / "wt")
    github = GitHubFalso()
    http_gh = github.cliente_http()
    cliente_gh = GitHubCliente(GitHubAppAuth("1", chave_pem, http_gh), http_gh)
    redis = fakeredis.FakeAsyncRedis()
    metricas = MetricasForja()
    sdk = SdkFalso()
    atividades = DeliveryActivities(
        ExecutorEco(
            sandbox, AgenteEco.com_sdk(sdk), RepositoriosLocais(tmp_path / "repos").caminho
        ),
        intervalo_heartbeat_s=0.2,
        publicador=PublicadorGitHub(cliente_gh, IdempotenciaRedis(redis), dry_run=False),
        metricas=metricas,
    )
    gateway = TemporalEntregaGateway(client)
    app = criar_app(
        DependenciasWebhook(
            ConfigWebhook(SEGREDO, 1_000_000),
            RegistroEntregasRedis(redis),
            AtivarEntrega(gateway, cliente_gh, frozenset({REPO})),
            metricas,
        ),
        DependenciasPanico("0" * 64, AcionarPanico(gateway)),
    )
    async with (
        criar_worker(client, atividades),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://forja") as http,
    ):
        yield Ambiente(http, github, sdk, sandbox, exp, metricas)
        # Entregas vizinhas usam a mesma issue (mesmo id): encerra o que ficou esperando.
        with contextlib.suppress(Exception):
            await client.get_workflow_handle(ID_ISSUE_42).terminate("fim do teste")
    await http_gh.aclose()


async def test_caminho_feliz_comenta_pelo_workflow_com_um_trace(amb: Ambiente, variante: str):
    resposta = await amb.webhook("issues_labeled_forja_intent", "e2e-feliz")
    assert resposta == {"status": "iniciada"}
    await esperar(lambda: len(amb.github.comentarios) == 1)

    c = amb.github.comentarios[0]
    assert c["repo"] == REPO and c["numero"] == 42 and "eco: corrigir login" in c["body"]
    # O agente roda sem ferramentas de escrita e sem cliente de GitHub: só o workflow publica.
    prompt, opts = amb.sdk.chamadas[0]
    assert "Corrigir login" in prompt and opts.allowed_tools == []
    assert "Bash" in opts.disallowed_tools
    if variante == "memoria":
        await esperar(lambda: bool(amb.sandbox.destruidos))
    spans = amb.spans.get_finished_spans()
    nomes = {s.name for s in spans}
    assert {"gateway.webhook", "agente.sessao"} <= nomes
    assert any("StartWorkflow" in n for n in nomes) and any("RunActivity" in n for n in nomes)
    ids = {s.context.trace_id for s in spans if s.context is not None}
    assert len(ids) == 1, f"esperava um trace só, vieram {len(ids)}: {sorted(nomes)}"
    sessao = next(s for s in spans if s.name == "agente.sessao")
    assert sessao.attributes is not None
    assert sessao.attributes["gen_ai.usage.output_tokens"] == 5
    assert "forja_entregas_iniciadas_total 1.0" in amb.metricas.exportar().decode()


async def test_entrega_repetida_nao_duplica_comentario_nem_execucao(amb: Ambiente):
    await amb.webhook("issues_labeled_forja_intent", "rep-1")
    await esperar(lambda: len(amb.github.comentarios) == 1)
    mesma_entrega = await amb.webhook("issues_labeled_forja_intent", "rep-1")
    novo_id = await amb.webhook("issues_labeled_forja_intent", "rep-2")
    await asyncio.sleep(0.5)

    assert mesma_entrega == {"status": "duplicada"}
    assert novo_id == {"status": "ja_existia"}
    assert len(amb.github.comentarios) == 1 and len(amb.sdk.chamadas) == 1


async def test_parar_cancela_o_workflow_e_destroi_o_sandbox(amb: Ambiente, variante: str):
    amb.sdk.atraso = 3600
    await amb.webhook("issues_labeled_forja_intent", "stop-1")
    await esperar(lambda: len(amb.sdk.chamadas) == 1)
    assert await amb.webhook("issue_comment_stop", "stop-2") == {"status": "sinalizada"}
    if variante == "memoria":
        await esperar(lambda: bool(amb.sandbox.destruidos))
        assert amb.sandbox.destruidos[-1] == amb.sandbox.criados[-1]
    else:
        await esperar(
            lambda: not subprocess.run(
                ["docker", "ps", "-aq", "--filter", "label=forja.sessao"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
        )  # fmt: skip
    assert amb.github.comentarios == []


async def test_comando_de_quem_nao_tem_escrita_e_ignorado(amb: Ambiente):
    amb.github.permissao = "read"
    resposta = await amb.webhook("issues_labeled_forja_intent", "sem-escrita")
    assert resposta == {"status": "ignorada"}
    assert amb.sdk.chamadas == [] and json.dumps(amb.github.comentarios) == "[]"
