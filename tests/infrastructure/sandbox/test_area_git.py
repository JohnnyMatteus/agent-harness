# pyright: basic
import os
import subprocess
from pathlib import Path

import pytest

from forja.application.portas.sandbox import SandboxError
from forja.domain.guardrails import Etapa, PoliticaDeSessao, auditar_mudancas
from forja.infrastructure.sandbox.area_git import AreaGit
from forja.infrastructure.sandbox.remoto_git import RemotoGitHub

ID = "0123456789abcdef"
BRANCH = f"forja/{ID}-corrige-login"


def sh(*args: str, cwd: Path) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}  # fmt: skip
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "wt"
    (r / "src").mkdir(parents=True)
    (r / "tests").mkdir()
    (r / "src" / "a.py").write_text("x = 1\n")
    (r / "tests" / "test_a.py").write_text("def test_a(): ...\n")
    sh("git", "init", "-q", "-b", "main", cwd=r)
    sh("git", "add", ".", cwd=r)
    sh("git", "commit", "-q", "-m", "base", cwd=r)
    return r


async def test_mudancas_incluem_nao_commitados_e_a_auditoria_pega_o_que_o_hook_nao_ve(
    repo: Path,
) -> None:
    area = AreaGit()
    base = await area.head(repo)
    (repo / "src" / "a.py").write_text("x = 2\n")
    (repo / "tests" / "test_a.py").write_text("def test_a(): assert True\n")  # trapaça por comando
    (repo / "feature_list.json").write_text("{}")
    (repo / "src" / "novo.py").write_text("y = 1\n")
    os.symlink("/etc/passwd", repo / "atalho")
    mudancas = {m.caminho: m for m in await area.mudancas(repo, base)}
    assert mudancas["src/a.py"].status == "M" and mudancas["src/novo.py"].status == "A"
    assert mudancas["atalho"].modo == "120000"
    testes = frozenset({"tests/test_a.py"})
    politica = PoliticaDeSessao(Etapa.EXECUTOR, ID, testes_existentes=testes)
    violacoes = auditar_mudancas(politica, mudancas.values())
    assert sorted(v.split(":")[0] for v in violacoes) == [
        "atalho",
        "feature_list.json",
        "tests/test_a.py",
    ]


async def test_descartar_volta_ao_base_e_apaga_o_que_a_sessao_criou(repo: Path) -> None:
    area = AreaGit()
    base = await area.head(repo)
    (repo / "src" / "a.py").write_text("lixo")
    (repo / "novo.txt").write_text("x")
    await area.descartar(repo, base)
    assert (repo / "src" / "a.py").read_text() == "x = 1\n" and not (repo / "novo.txt").exists()
    assert await area.commitar(repo, "nada") is None


async def test_commit_leva_a_mensagem_inteira_com_trailers(repo: Path) -> None:
    area = AreaGit()
    (repo / "src" / "b.py").write_text("z")
    sha = await area.commitar(repo, f"forja(exec): f1\n\nIntent-Id: {ID}\nRun-Id: r")
    assert sha and f"Intent-Id: {ID}" in sh("git", "log", "-1", "--format=%B", cwd=repo)
    assert "Forja" in sh("git", "log", "-1", "--format=%an", cwd=repo)
    assert "forja(exec)" in await area.log_recente(repo, 3)


async def test_hook_do_repositorio_nao_executa_no_commit(repo: Path) -> None:
    gancho = repo / ".git" / "hooks" / "pre-commit"
    gancho.write_text("#!/bin/sh\ntouch /tmp/forja-hook-executou-$$\nexit 1\n")
    gancho.chmod(0o755)
    (repo / "src" / "b.py").write_text("z")
    assert await AreaGit().commitar(repo, "m")  # o hook (que falharia) foi ignorado


async def test_link_para_fora_do_worktree_recusa_e_interno_e_protegido(repo: Path) -> None:
    area = AreaGit()
    os.symlink("src/a.py", repo / "interno")
    testes, links = await area.arquivos_de_teste_e_links(repo)
    assert testes == {"tests/test_a.py"} and links == {"interno"}
    os.symlink("/etc", repo / "fora")
    with pytest.raises(SandboxError, match="fora do worktree"):
        await area.arquivos_de_teste_e_links(repo)


async def test_escrita_do_harness_recusa_caminho_e_link(repo: Path) -> None:
    area = AreaGit()
    await area.escrever(repo, f".forja/{ID}/progress.md", "ok")
    assert await area.ler(repo, f".forja/{ID}/progress.md") == "ok"
    from forja.domain.artefatos import ArtefatoInvalido

    with pytest.raises(ArtefatoInvalido):
        await area.escrever(repo, "../fora", "x")
    os.symlink(repo / "src", repo / "d")
    with pytest.raises(SandboxError):
        await area.escrever(repo, "d/x.py", "x")


async def test_fetch_e_push_da_branch_da_entrega_contra_um_remoto_local(
    repo: Path, tmp_path: Path
) -> None:
    remotos = tmp_path / "remotos"
    bare = remotos / "acme" / "loja"
    bare.mkdir(parents=True)
    sh("git", "init", "-q", "--bare", "-b", "main", cwd=bare)
    sh("git", "push", "-q", str(bare), "HEAD:refs/heads/main", cwd=repo)
    remoto = RemotoGitHub(None, base=str(remotos), dry_run=False)
    area = AreaGit()

    assert await remoto.buscar("acme/loja", BRANCH, repo) is False  # ainda não existe
    sh("git", "switch", "-q", "-c", BRANCH, cwd=repo)
    (repo / "src" / "b.py").write_text("z")
    await area.commitar(repo, "f1")
    await remoto.enviar("acme/loja", BRANCH, repo)
    assert BRANCH in sh("git", "branch", "--list", cwd=bare)

    outro = tmp_path / "outro"
    sh("git", "clone", "-q", str(bare), str(outro), cwd=tmp_path)
    assert await remoto.buscar("acme/loja", BRANCH, outro) is True
    assert (outro / "src" / "b.py").read_text() == "z"


@pytest.mark.parametrize(
    "branch", ["main", "forja/", "forja/x;rm", "forja/../main", "release/x", "forja/A"]
)
async def test_push_recusa_branch_que_nao_e_da_entrega(repo: Path, branch: str) -> None:
    remoto = RemotoGitHub(None, base="/nao-usado", dry_run=False)
    with pytest.raises(SandboxError, match="branch recusada"):
        await remoto.enviar("acme/loja", branch, repo)


async def test_dry_run_nao_toca_o_remoto_e_token_nunca_vai_em_argumento(repo: Path) -> None:
    chamado = []

    class Auth:
        async def token_de_instalacao(self, repositorio: str) -> str:
            chamado.append(repositorio)
            return "ghs_TOKEN_SECRETO"

    seco = RemotoGitHub(Auth(), dry_run=True)
    await seco.enviar("acme/loja", BRANCH, repo)
    assert await seco.buscar("acme/loja", BRANCH, repo) is False and chamado == []
    real = RemotoGitHub(Auth(), dry_run=False)
    env = await real._ambiente("acme/loja")
    assert "ghs_TOKEN_SECRETO" not in real._url("acme/loja")
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    with pytest.raises(SandboxError, match="inválido"):
        real._url("../x")
