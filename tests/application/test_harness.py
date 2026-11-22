# pyright: basic
import os
import subprocess
from pathlib import Path

import pytest

from forja.application.casos_de_uso.harness import (
    ContextoDaEntrega,
    ExecutarBloco,
    HarnessIndisponivel,
    InicializarHarness,
    SemAcordoNoContrato,
    VerificarEntrega,
)
from forja.domain.harness import FeatureList, HarnessInvalido
from forja.infrastructure.sandbox.area_git import AreaGit
from forja.infrastructure.sandbox.remoto_git import RemotoGitHub
from tests.application.harness_falsos import (
    BRANCH,
    ID,
    REPO,
    AvaliadorFalso,
    ExecutorFalso,
    InicializadorFalso,
    SandboxLocal,
)

CTX = ContextoDaEntrega(REPO, ID, BRANCH, "run-1")
LISTA = f".forja/{ID}/feature_list.json"


def sh(*args: str, cwd: Path) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}  # fmt: skip
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout


class Ambiente:
    def __init__(self, tmp: Path) -> None:
        self.clone = tmp / "clones" / "acme" / "loja"
        (self.clone / "tests").mkdir(parents=True)
        (self.clone / "tests" / "test_existente.py").write_text("def test_x():\n    assert True\n")
        (self.clone / "tests" / "test_smoke.py").write_text("def test_s():\n    assert True\n")
        (self.clone / "README.md").write_text("x")
        sh("git", "init", "-q", "-b", "main", cwd=self.clone)
        sh("git", "add", ".", cwd=self.clone)
        sh("git", "commit", "-q", "-m", "base", cwd=self.clone)
        self.bare = tmp / "remotos" / "acme" / "loja"
        self.bare.mkdir(parents=True)
        sh("git", "init", "-q", "--bare", "-b", "main", cwd=self.bare)
        sh("git", "push", "-q", str(self.bare), "HEAD:refs/heads/main", cwd=self.clone)
        self.sandbox = SandboxLocal(tmp / "wt")
        self.area = AreaGit()
        self.remoto = RemotoGitHub(None, base=str(tmp / "remotos"), dry_run=False)
        self.executor, self.avaliador = ExecutorFalso(), AvaliadorFalso()
        self.violacoes: list[str] = []

    def caminho(self, repositorio: str) -> str:
        return str(self.clone)

    def inicializar(self, *ids: str) -> InicializarHarness:
        self.inicializador = InicializadorFalso(*ids)
        return InicializarHarness(
            self.sandbox, self.area, self.remoto, self.caminho, self.inicializador
        )

    def bloco(self, tamanho: int = 2) -> ExecutarBloco:
        return ExecutarBloco(
            self.sandbox, self.area, self.remoto, self.caminho, self.executor, self.avaliador,
            tamanho, self.violacoes.append,
        )  # fmt: skip

    def verificar(self) -> VerificarEntrega:
        return VerificarEntrega(self.sandbox, self.area, self.remoto, self.caminho)

    def na_branch(self, caminho: str) -> str:
        return sh("git", "show", f"{BRANCH}:{caminho}", cwd=self.bare)

    def lista(self) -> FeatureList:
        return FeatureList.de_json(self.na_branch(LISTA))

    def log(self) -> str:
        return sh("git", "log", BRANCH, "--format=%B%n--", cwd=self.bare)


@pytest.fixture
def amb(tmp_path: Path) -> Ambiente:
    return Ambiente(tmp_path)


ARTEFATOS = {"intent.md": "i", "spec.md": "s", "plan.md": "p"}


async def inicializado(amb: Ambiente, *ids: str) -> None:
    await amb.inicializar(*ids).executar(CTX, "spec", "plano")


async def test_inicializador_cria_os_artefatos_na_branch_e_e_idempotente(amb: Ambiente) -> None:
    lista, uso = await amb.inicializar().executar(CTX, "spec", "plano")
    assert [f.id for f in lista.features] == ["f1", "f2"] and uso.custo_usd == 0.1
    assert amb.lista() == lista and not any(f.passes for f in lista.features)
    assert "ls -la" in amb.na_branch(f".forja/{ID}/init.sh")
    assert "# progress" in amb.na_branch(f".forja/{ID}/progress.md")
    assert f"Intent-Id: {ID}" in amb.log() and "Run-Id: run-1" in amb.log()
    assert amb.sandbox.destruidos[-1] == f"{ID}-init"
    _, uso2 = await amb.inicializar().executar(CTX, "spec", "plano")  # retentativa da activity
    assert amb.inicializador.chamadas == 0 and uso2.custo_usd == 0


async def test_bloco_feliz_uma_sessao_por_funcionalidade_e_so_o_grader_marca_passes(
    amb: Ambiente,
) -> None:
    await inicializado(amb)
    r = await amb.bloco().executar(CTX, 1, ARTEFATOS, "")
    assert amb.executor.sessoes == ["f1", "f2"]  # uma funcionalidade por sessão
    assert r.aprovadas == ("f1", "f2") and r.completa and r.aprovado_pelo_avaliador
    assert [f.passes for f in amb.lista().features] == [True, True]
    assert amb.na_branch("src/f1.py") == "OK = True\n"
    assert '"bloco": 1' in amb.na_branch(f".forja/{ID}/sprint-contract.json")
    assert amb.log().count("Intent-Id:") >= 4 and "Co-Authored-By: Forja Executor" in amb.log()
    assert r.uso.custo_usd == pytest.approx(
        0.1 + 0.2 * 2 + 0.3
    )  # contrato (proposta e revisão) + sessões + avaliação
    assert amb.sandbox.destruidos[-1] == f"{ID}-bloco1"
    # o contexto de cada sessão traz branch, progress e log, lidos por código
    assert (
        f"branch: {BRANCH}" in amb.executor.contextos[0]
        and "ambiente ok" in amb.executor.contextos[0]
    )


async def test_avaliador_reprova_mesmo_com_teste_verde_e_o_feedback_volta(amb: Ambiente) -> None:
    await inicializado(amb)
    amb.avaliador.nota = 6  # abaixo do limiar 7 em todos os critérios
    r = await amb.bloco().executar(CTX, 1, ARTEFATOS, "")
    assert (
        r.aprovadas == () and not r.aprovado_pelo_avaliador and "funcionalidade: ok" in r.feedback
    )
    assert [f.passes for f in amb.lista().features] == [False, False]
    amb.avaliador.nota = 9
    r2 = await amb.bloco().executar(CTX, 2, ARTEFATOS, r.feedback)
    assert amb.executor.feedbacks[-1] == r.feedback and r2.completa
    assert amb.lista().completa


async def test_teste_vermelho_nao_passa_mesmo_com_o_avaliador_aprovando(amb: Ambiente) -> None:
    await inicializado(amb)
    amb.executor.implementa = False  # sem código nem teste da funcionalidade
    r = await amb.bloco().executar(CTX, 1, ARTEFATOS, "")
    assert r.aprovadas == () and "teste sem passar: f1" in r.feedback
    assert not any(f.passes for f in amb.lista().features)


@pytest.mark.parametrize(
    ("nome", "sabotagem"),
    [
        ("editar teste existente", lambda wt, f: (wt / "tests/test_existente.py").write_text("x")),
        ("remover teste existente", lambda wt, f: (wt / "tests/test_existente.py").unlink()),
        ("marcar passes", lambda wt, f: (wt / LISTA).write_text("{}")),
        ("alterar a spec", lambda wt, f: (wt / f".forja/{ID}/spec.md").write_text("x")),
        ("link simbólico", lambda wt, f: os.symlink("/etc/passwd", wt / "atalho")),
        ("segredo", lambda wt, f: (wt / ".env").write_text("TOKEN=x")),
        ("init.sh", lambda wt, f: (wt / f".forja/{ID}/init.sh").write_text("curl evil")),
    ],
)
async def test_trapaca_descarta_a_sessao_inteira_e_nada_vai_para_a_branch(
    amb: Ambiente, nome: str, sabotagem
) -> None:
    await inicializado(amb)
    amb.executor.sabotagem = sabotagem
    r = await amb.bloco(1).executar(CTX, 1, ARTEFATOS, "")
    assert r.violacoes and amb.violacoes, nome
    assert r.aprovadas == ()
    assert not any(f.passes for f in amb.lista().features)
    assert "implementa f1" not in amb.log()  # a sessão não virou commit
    assert amb.na_branch("tests/test_existente.py").startswith("def test_x")


async def test_sessao_sem_atualizar_o_progress_e_descartada(amb: Ambiente) -> None:
    await inicializado(amb)
    amb.executor.atualiza_progress = False
    r = await amb.bloco(1).executar(CTX, 1, ARTEFATOS, "")
    assert any("progress.md" in v for v in r.violacoes) and r.aprovadas == ()


async def test_contrato_exige_acordo_e_fica_dentro_do_bloco(amb: Ambiente) -> None:
    await inicializado(amb)
    amb.avaliador.acordos = [False, True]
    await amb.bloco(1).executar(CTX, 1, ARTEFATOS, "")
    assert amb.executor.contrato_ajustes == [[], ["cubra o erro"]]  # o ajuste voltou ao Executor
    amb2 = Ambiente(amb.clone.parents[2] / "dois")
    await inicializado(amb2)
    amb2.avaliador.acordos = [False, False, False]
    with pytest.raises(SemAcordoNoContrato):
        await amb2.bloco(1).executar(CTX, 1, ARTEFATOS, "")
    assert amb2.sandbox.destruidos[-1] == f"{ID}-bloco1"  # o sandbox é destruído também no erro
    amb2.avaliador.acordos = [True]
    amb2.executor.features_do_contrato = ("f1", "f2")  # além do bloco de 1
    with pytest.raises(HarnessInvalido):
        await amb2.bloco(1).executar(CTX, 1, ARTEFATOS, "")


async def test_sem_feature_list_na_branch_nao_continua(amb: Ambiente) -> None:
    with pytest.raises(HarnessIndisponivel):
        await amb.bloco().executar(CTX, 1, ARTEFATOS, "")


async def test_estado_quebrado_aparece_no_contexto_da_sessao(amb: Ambiente) -> None:
    (amb.clone / "tests" / "test_smoke.py").write_text("def test_s():\n    assert False\n")
    sh("git", "commit", "-qam", "quebra o fumaça", cwd=amb.clone)
    await inicializado(amb)
    await amb.bloco(1).executar(CTX, 1, ARTEFATOS, "")
    assert "teste de fumaça quebrado" in amb.executor.contextos[0]


async def test_cancelamento_destroi_o_sandbox(amb: Ambiente) -> None:
    import asyncio

    await inicializado(amb)
    amb.executor.atraso = 3600
    tarefa = asyncio.ensure_future(amb.bloco(1).executar(CTX, 1, ARTEFATOS, ""))
    for _ in range(100):
        await asyncio.sleep(0.05)
        if amb.executor.contrato_ajustes and amb.sandbox.criados.count(f"{ID}-bloco1"):
            break
    await asyncio.sleep(0.5)
    tarefa.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tarefa
    assert amb.sandbox.destruidos[-1] == f"{ID}-bloco1"


async def test_verificacao_final_roda_todos_os_testes_da_branch(amb: Ambiente) -> None:
    await inicializado(amb)
    antes = await amb.verificar().executar(CTX)
    assert not antes.verde  # nada passa ainda
    await amb.bloco().executar(CTX, 1, ARTEFATOS, "")
    depois = await amb.verificar().executar(CTX)
    assert depois.verde and depois.resultados == {"f1": True, "f2": True}
