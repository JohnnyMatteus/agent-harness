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


@pytest_asyncio.fixture(loop_scope="module")
async def amb_h(temporal, chave_pem, tmp_path, monkeypatch):
    montagem = Montagem(tmp_path)
    async with ambiente(
        temporal, chave_pem, tmp_path, monkeypatch, lambda _: montagem.harness
    ) as a:
        a.montagem = montagem  # type: ignore[attr-defined]
        a.sdk.pontos = []
        yield a


async def _ate_o_build(amb: Ambiente, entrega: str) -> None:
    await amb.rotular(entrega)
    await esperar(lambda: any("/forja confirm" in c for c in amb.comentarios()))
    await amb.comentar("/forja confirm", entrega + "-c")


async def test_do_webhook_ao_pr_verificado_com_git_real(amb_h: Ambiente) -> None:
    m: Montagem = amb_h.montagem  # type: ignore[attr-defined]
    await _ate_o_build(amb_h, "h1")
    await esperar(lambda: len(amb_h.github.prs) == 1, 60)
    # O PR abre ANTES do comentário final e do registro do desfecho (a última activity do
    # workflow): quem confere isso precisa esperar a condição, não o PR.
    await esperar(lambda: any("Verificação verde" in c for c in amb_h.comentarios()), 60)
    await esperar(
        lambda: "forja_entregas_concluidas_total 1.0" in amb_h.metricas.exportar().decode(), 60
    )

    lista = FeatureList.de_json(m.na_branch(f".forja/{ID}/feature_list.json"))
    assert [f.passes for f in lista.features] == [True, True]
    assert m.na_branch("src/f1.py") == "OK = True\n"
    assert '"bloco": 1' in m.na_branch(f".forja/{ID}/sprint-contract.json")
    log = m.git("log", BRANCH, "--format=%B", cwd=m.bare)
    assert f"Intent-Id: {ID}" in log and "Co-Authored-By: Forja Executor" in log
    assert "feature_list.json" not in m.git("log", BRANCH, "--format=%an", cwd=m.bare)
    assert "passaram na verificação" in amb_h.github.prs[0]["body"]
    assert any("Bloco 1: aprovadas f1, f2" in c for c in amb_h.comentarios())
    assert any("Verificação verde" in c for c in amb_h.comentarios())
    assert m.sandbox.criados and set(m.sandbox.criados) == set(m.sandbox.destruidos)
    texto = amb_h.metricas.exportar().decode()
    assert "forja_custo_usd_total" in texto and "forja_entregas_concluidas_total 1.0" in texto
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
