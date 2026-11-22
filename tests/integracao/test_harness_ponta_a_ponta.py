"""M4 ponta a ponta: do webhook ao PR verificado, com git real (remoto bare local), sandbox
local, GitHub falso e agentes roteirizados. Mesmo caminho do M3, depois o Build de longa duração:
Inicializador, bloco com contrato e Avaliador, grader de código, verificação final e PR."""

# pyright: basic
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import pytest_asyncio

from forja.application.casos_de_uso.harness import (
    ExecutarBloco,
    HarnessDaEntrega,
    InicializarHarness,
    VerificarEntrega,
)
from forja.domain.harness import FeatureList
from forja.infrastructure.sandbox.area_git import AreaGit
from forja.infrastructure.sandbox.remoto_git import RemotoGitHub
from forja.infrastructure.sandbox.repositorios import RepositoriosLocais
from tests.application.harness_falsos import (
    AvaliadorFalso,
    ExecutorFalso,
    InicializadorFalso,
    SandboxLocal,
)
from tests.integracao.test_sdlc_ponta_a_ponta import (
    BRANCH,
    ID,
    REPO,
    Ambiente,
    ambiente,
    esperar,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")


class Montagem:
    def __init__(self, tmp: Path) -> None:
        remotos = tmp / "remotos"
        self.bare = remotos / REPO
        self.bare.mkdir(parents=True)
        self.git("init", "-q", "--bare", "-b", "main", cwd=self.bare)
        self.sandbox = SandboxLocal(tmp / "wt")
        self.executor, self.avaliador = ExecutorFalso(), AvaliadorFalso()
        self.violacoes: list[str] = []
        repos = RepositoriosLocais(tmp / "repos")
        area, remoto = AreaGit(), RemotoGitHub(None, base=str(remotos), dry_run=False)
        self.harness = HarnessDaEntrega(
            InicializarHarness(self.sandbox, area, remoto, repos.caminho, InicializadorFalso()),
            ExecutarBloco(
                self.sandbox,
                area,
                remoto,
                repos.caminho,
                self.executor,
                self.avaliador,
                2,
                self.violacoes.append,
            ),
            VerificarEntrega(self.sandbox, area, remoto, repos.caminho),
        )

    @staticmethod
    def git(*args: str, cwd: Path) -> str:
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}  # fmt: skip
        return subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env
        ).stdout

    def na_branch(self, caminho: str) -> str:
        return self.git("show", f"{BRANCH}:{caminho}", cwd=self.bare)


POLITICA_BAIXA = 'risk_tiers:\n  low:\n    paths: ["**"]\n'


def _arquivos_do_diff() -> list[dict]:
    return [
        {
            "filename": "src/f1.py",
            "status": "added",
            "additions": 1,
            "deletions": 0,
            "patch": "+OK = True",
        },
        {
            "filename": "tests/test_f1.py",
            "status": "added",
            "additions": 3,
            "deletions": 0,
            "patch": "+def test_ok(): ...",
        },
    ]


@pytest_asyncio.fixture(loop_scope="module")
async def amb_h(temporal, chave_pem, tmp_path, monkeypatch):
    montagem = Montagem(tmp_path)
    async with ambiente(
        temporal, chave_pem, tmp_path, monkeypatch, lambda _: montagem.harness
    ) as a:
        a.montagem = montagem  # type: ignore[attr-defined]
        a.sdk.pontos = []
        a.github.arquivos_do_diff = _arquivos_do_diff()
        yield a


@pytest_asyncio.fixture(loop_scope="module")
async def amb_automerge(temporal, chave_pem, tmp_path, monkeypatch):
    import base64

    montagem = Montagem(tmp_path)
    async with ambiente(
        temporal, chave_pem, tmp_path, monkeypatch, lambda _: montagem.harness,
        automerge=frozenset({REPO}),
    ) as a:  # fmt: skip
        a.montagem = montagem  # type: ignore[attr-defined]
        a.sdk.pontos = []
        a.github.arquivos_do_diff = _arquivos_do_diff()
        a.github.arquivos[("main", ".forja/policy.yaml")] = {
            "content": base64.b64encode(POLITICA_BAIXA.encode()).decode(),
            "sha": "p",
        }
        yield a


async def _ate_o_build(amb: Ambiente, entrega: str) -> None:
    await amb.rotular(entrega)
    await esperar(lambda: any("/forja confirm" in c for c in amb.comentarios()))
    await amb.comentar("/forja confirm", entrega + "-c")


async def test_do_webhook_ao_pr_verificado_com_git_real(amb_h: Ambiente) -> None:
    m: Montagem = amb_h.montagem  # type: ignore[attr-defined]
    await _ate_o_build(amb_h, "h1")
    await esperar(lambda: len(amb_h.github.prs) == 1, 60)
    await esperar(lambda: any("Um humano decide" in c for c in amb_h.comentarios()), 60)

    lista = FeatureList.de_json(m.na_branch(f".forja/{ID}/feature_list.json"))
    assert [f.passes for f in lista.features] == [True, True]
    assert m.na_branch("src/f1.py") == "OK = True\n"
    assert '"bloco": 1' in m.na_branch(f".forja/{ID}/sprint-contract.json")
    log = m.git("log", BRANCH, "--format=%B", cwd=m.bare)
    assert f"Intent-Id: {ID}" in log and "Co-Authored-By: Forja Executor" in log
    assert "feature_list.json" not in m.git("log", BRANCH, "--format=%an", cwd=m.bare)
    assert "passaram na verificação" in amb_h.github.prs[0]["body"]
    assert any("Bloco 1: aprovadas f1, f2" in c for c in amb_h.comentarios())
    assert any("Um humano decide" in c for c in amb_h.comentarios())
    assert m.sandbox.criados and set(m.sandbox.criados) == set(m.sandbox.destruidos)
    # A entrega só termina depois da aprovação humana; o desfecho é a última activity.
    await amb_h.comentar("/forja approve", "h1-a")
    await esperar(
        lambda: "forja_entregas_concluidas_total 1.0" in amb_h.metricas.exportar().decode(), 60
    )
    assert "forja_custo_usd_total" in amb_h.metricas.exportar().decode()
    spans = amb_h.spans.get_finished_spans()
    inicio = next(s for s in spans if "StartWorkflow" in s.name)
    raiz = getattr(inicio.context, "trace_id", None)
    nomes = {s.name for s in spans if getattr(s.context, "trace_id", 0) == raiz}
    assert {"RunActivity:harness_inicializar", "RunActivity:harness_bloco"} <= nomes


async def test_sessao_que_trapaceia_e_descartada_e_a_entrega_falha_para_um_humano(
    amb_h: Ambiente,
) -> None:
    m: Montagem = amb_h.montagem  # type: ignore[attr-defined]
    m.executor.sabotagem = lambda wt, f: (wt / "tests" / "test_smoke.py").write_text("trapaça")
    await _ate_o_build(amb_h, "h2")
    await esperar(lambda: any("interrompida" in c for c in amb_h.comentarios()), 90)
    assert amb_h.github.prs == [] and m.violacoes
    lista = FeatureList.de_json(m.na_branch(f".forja/{ID}/feature_list.json"))
    assert not any(f.passes for f in lista.features)
    assert m.na_branch("tests/test_smoke.py") == "def test_s():\n    assert True\n"
    assert any("tests/test_smoke.py" in v for v in m.violacoes)


async def test_revisao_check_runs_e_aprovacao_humana_sem_politica_declarada(
    amb_h: Ambiente,
) -> None:
    await _ate_o_build(amb_h, "r1")
    await esperar(lambda: any("Um humano decide" in c for c in amb_h.comentarios()), 90)
    # sem .forja/policy.yaml na branch padrão: nada é baixo risco, mesmo com auto-merge possível
    assert "risco alto" in " ".join(amb_h.comentarios()) and amb_h.github.merges == []
    nomes = [c["name"] for c in amb_h.github.check_runs]
    assert sorted(nomes) == ["forja/adrs", "forja/desempenho", "forja/seguranca", "forja/testes"]
    assert {c["head_sha"] for c in amb_h.github.check_runs} == {amb_h.github.ref_final}
    assert all(c["conclusion"] == "success" for c in amb_h.github.check_runs)
    # review.md vai pela API de conteúdo do GitHub (falso aqui), não pelo git do worktree
    assert "# review" in amb_h.github.arquivo(BRANCH, f".forja/{ID}/review.md")
    await amb_h.comentar("/forja approve", "r1-a")
    await esperar(lambda: any("Aprovado por" in c for c in amb_h.comentarios()), 30)
    assert amb_h.github.prontos == ["PR_1"] and amb_h.github.merges == []  # o merge é humano


async def test_risco_baixo_com_politica_declarada_e_auto_merge_habilitado_mescla(
    amb_automerge: Ambiente,
) -> None:
    amb = amb_automerge
    # o CI do repositório (check externo) já passou nesse commit; os checks da Forja não bastam
    amb.github.check_runs.append(
        {"name": "ci/build", "head_sha": amb.github.ref_final, "status": "completed",
         "conclusion": "success"}
    )  # fmt: skip
    await _ate_o_build(amb, "m1")
    await esperar(lambda: any("PR mesclado" in c for c in amb.comentarios()), 90)
    assert len(amb.github.merges) == 1 and amb.github.merges[0]["sha"] == amb.github.ref_final
    assert amb.github.merges[0]["merge_method"] == "squash" and amb.github.prontos == ["PR_1"]
    await esperar(  # o desfecho é a última activity, depois do comentário final
        lambda: "forja_entregas_concluidas_total 1.0" in amb.metricas.exportar().decode(), 60
    )


async def test_segredo_no_diff_barra_a_entrega_mesmo_com_o_modelo_dizendo_que_esta_tudo_bem(
    amb_automerge: Ambiente,
) -> None:
    amb = amb_automerge
    amb.github.arquivos_do_diff[0]["patch"] = "+TOKEN = 'ghp_" + "a" * 30 + "'"
    await _ate_o_build(amb, "s1")
    await esperar(lambda: any("achados bloqueantes" in c for c in amb.comentarios()), 90)
    seg = next(c for c in amb.github.check_runs if c["name"] == "forja/seguranca")
    assert seg["conclusion"] == "failure" and seg["output"]["annotations"][0]["path"] == "src/f1.py"
    assert amb.github.merges == [] and amb.github.prontos == []


async def test_so_com_os_checks_da_propria_forja_nao_ha_auto_merge(amb_automerge: Ambiente) -> None:
    amb = amb_automerge  # política baixa e repositório habilitado, mas nenhum check externo
    await _ate_o_build(amb, "x1")
    await esperar(lambda: any("Um humano decide" in c for c in amb.comentarios()), 90)
    assert amb.github.merges == [] and len(amb.github.check_runs) == 4
