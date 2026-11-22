# pyright: basic
"""Git do host sobre um worktree que o container escreve. Cada ataque usa um comando inofensivo
(`touch` de um marcador em diretório temporário) e prova que nada executa no host."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from forja.application.portas.sandbox import SandboxError
from forja.domain.guardrails import Etapa, PoliticaDeSessao, auditar_mudancas
from forja.infrastructure.sandbox.area_git import AreaGit
from forja.infrastructure.sandbox.remoto_git import RemotoGitHub
from forja.infrastructure.sandbox.worktree import GerenciadorWorktree

ID = "0123456789abcdef"
BRANCH = f"forja/{ID}-corrige-login"


def sh(*args: str, cwd: Path) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}  # fmt: skip
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout


@pytest.fixture
def origem(tmp_path: Path) -> Path:
    r = tmp_path / "clone"
    (r / "src").mkdir(parents=True)
    (r / "tests").mkdir()
    (r / "src" / "a.py").write_text("x = 1\n")
    (r / "tests" / "test_a.py").write_text("def test_a(): ...\n")
    sh("git", "init", "-q", "-b", "main", cwd=r)
    sh("git", "add", ".", cwd=r)
    sh("git", "commit", "-q", "-m", "base", cwd=r)
    return r


@pytest.fixture
async def repo(origem: Path, tmp_path: Path) -> Path:
    """Um worktree vinculado de verdade, com o gitdir registrado na criação."""
    return await GerenciadorWorktree(tmp_path / "wt").criar("s1", origem)


@pytest.fixture
def marcador(tmp_path: Path) -> Path:
    return tmp_path / "executou-no-host"


def armar_filtro(repo: Path, marcador: Path, onde: str = ".gitconfig") -> None:
    """O que o agente escreveria: um filtro `clean` e o .gitattributes que o aciona."""
    (repo / onde).parent.mkdir(parents=True, exist_ok=True)
    (repo / onde).write_text(f'[filter "x"]\n\tclean = touch {marcador}\n')
    (repo / ".gitattributes").write_text("* filter=x\n")
    (repo / "src" / "novo.py").write_text("y = 1\n")


async def test_gitconfig_no_worktree_nao_vira_configuracao_do_git_do_host(
    repo: Path, marcador: Path
) -> None:
    for onde in (".gitconfig", ".config/git/config"):
        armar_filtro(repo, marcador, onde)
        base = await AreaGit().head(repo)
        await AreaGit().mudancas(repo, base)
        await AreaGit().commitar(repo, "m")
        assert not marcador.exists(), f"{onde} executou no host"


async def test_ponteiro_git_trocado_por_repositorio_falso_e_recusado(
    repo: Path, tmp_path: Path, marcador: Path
) -> None:
    falso = tmp_path / "falso"
    sh("git", "init", "-q", str(falso), cwd=tmp_path)
    (falso / "config").write_text(
        f'[core]\n\trepositoryformatversion = 0\n[filter "x"]\n\tclean = touch {marcador}\n'
    )
    (repo / ".git").unlink()
    (repo / ".git").write_text(f"gitdir: {falso}/.git\n")
    (repo / ".gitattributes").write_text("* filter=x\n")
    (repo / "src" / "novo.py").write_text("y = 1\n")
    with pytest.raises(SandboxError, match=r"ponteiro \.git"):
        await AreaGit().mudancas(repo, "HEAD")
    assert not marcador.exists()


@pytest.mark.parametrize("troca", ["diretorio", "link", "removido"])
async def test_git_que_deixou_de_ser_o_arquivo_registrado_e_recusado(
    repo: Path, troca: str
) -> None:
    (repo / ".git").unlink()
    if troca == "diretorio":
        (repo / ".git").mkdir()
    elif troca == "link":
        os.symlink("/tmp", repo / ".git")
    with pytest.raises(SandboxError, match=r"ponteiro \.git"):
        await AreaGit().head(repo)


async def test_git_aninhado_e_gitlink_sao_recusados_antes_de_qualquer_git_e_descartados(
    repo: Path, tmp_path: Path, marcador: Path
) -> None:
    aninhado = repo / "vendor" / "lib"
    sh("git", "init", "-q", str(aninhado), cwd=tmp_path)
    (aninhado / ".git" / "config").write_text(f'[filter "x"]\n\tclean = touch {marcador}\n')
    (aninhado / "a.py").write_text("x")
    (repo / ".gitattributes").write_text("* filter=x\n")
    area = AreaGit()
    base = await area.head(repo)
    with pytest.raises(SandboxError, match="aninhado"):
        await area.mudancas(repo, base)
    with pytest.raises(SandboxError, match="aninhado"):
        await area.commitar(repo, "m")
    assert not marcador.exists()
    await area.descartar(repo, base)  # remove o .git aninhado e volta ao base
    assert not (repo / "vendor").exists() and not marcador.exists()
    assert await area.commitar(repo, "nada") is None


async def test_link_em_diretorio_intermediario_nao_e_seguido_na_leitura_nem_na_escrita(
    repo: Path, tmp_path: Path
) -> None:
    fora = tmp_path / "fora"
    fora.mkdir()
    (fora / "segredo.md").write_text("segredo do host")
    os.symlink(fora, repo / "dir")
    area = AreaGit()
    with pytest.raises(SandboxError, match="link simbólico"):
        await area.ler(repo, "dir/segredo.md")
    with pytest.raises(SandboxError, match="link"):
        await area.escrever(repo, "dir/novo.md", "x")
    with pytest.raises(SandboxError, match="link"):
        await area.escrever(repo, "dir/sub/novo.md", "x")
    assert sorted(p.name for p in fora.iterdir()) == ["segredo.md"]
    os.symlink("src/a.py", repo / "atalho.md")  # link no último componente
    with pytest.raises(SandboxError, match="link simbólico"):
        await area.ler(repo, "atalho.md")


async def test_escrita_e_leitura_normais_criam_diretorios_e_nao_vazam_o_teto(repo: Path) -> None:
    area = AreaGit()
    await area.escrever(repo, f".forja/{ID}/progress.md", "ok")
    assert await area.ler(repo, f".forja/{ID}/progress.md") == "ok"
    assert await area.ler(repo, "nao/existe.md") is None
    (repo / "grande.md").write_text("x" * 300_000)
    with pytest.raises(SandboxError, match="teto"):
        await area.ler(repo, "grande.md")
    from forja.domain.artefatos import ArtefatoInvalido

    with pytest.raises(ArtefatoInvalido):
        await area.escrever(repo, "../fora", "x")


async def test_worktree_sem_registro_de_gitdir_falha_fechado(origem: Path, tmp_path: Path) -> None:
    solto = tmp_path / "solto"
    sh("git", "worktree", "add", "--detach", str(solto), "HEAD", cwd=origem)
    with pytest.raises(SandboxError, match="sem gitdir registrado"):
        await AreaGit().head(solto)


async def test_mudancas_e_auditoria_pegam_o_que_o_hook_nao_ve(repo: Path) -> None:
    area = AreaGit()
    base = await area.head(repo)
    (repo / "src" / "a.py").write_text("x = 2\n")
    (repo / "tests" / "test_a.py").write_text("def test_a(): assert True\n")
    (repo / "feature_list.json").write_text("{}")
    (repo / "src" / "novo.py").write_text("y = 1\n")
    os.symlink("/etc/passwd", repo / "atalho")
    mudancas = {m.caminho: m for m in await area.mudancas(repo, base)}
    assert mudancas["src/a.py"].status == "M" and mudancas["src/novo.py"].status == "A"
    assert mudancas["atalho"].modo == "120000"
    politica = PoliticaDeSessao(
        Etapa.EXECUTOR, ID, testes_existentes=frozenset({"tests/test_a.py"})
    )
    violacoes = auditar_mudancas(politica, mudancas.values())
    assert sorted(v.split(":")[0] for v in violacoes) == [
        "atalho",
        "feature_list.json",
        "tests/test_a.py",
    ]


async def test_descartar_volta_ao_base_e_apaga_inclusive_o_que_o_gitignore_esconde(
    repo: Path,
) -> None:
    area = AreaGit()
    base = await area.head(repo)
    (repo / "src" / "a.py").write_text("lixo")
    (repo / "novo.txt").write_text("x")
    (repo / ".venv").mkdir()
    (repo / ".venv" / "forjado").write_text("x")
    await area.descartar(repo, base)
    assert (repo / "src" / "a.py").read_text() == "x = 1\n"
    assert not (repo / "novo.txt").exists() and not (repo / ".venv").exists()


async def test_commit_leva_a_mensagem_com_trailers_e_ignora_hook_do_clone(
    repo: Path, origem: Path
) -> None:
    gancho = origem / ".git" / "hooks" / "pre-commit"
    gancho.write_text("#!/bin/sh\nexit 1\n")
    gancho.chmod(0o755)
    (repo / "src" / "b.py").write_text("z")
    sha = await AreaGit().commitar(repo, f"forja(exec): f1\n\nIntent-Id: {ID}\nRun-Id: r")
    assert sha and f"Intent-Id: {ID}" in sh("git", "log", "-1", "--format=%B", cwd=repo)


async def test_fetch_e_push_da_branch_nao_leem_configuracao_do_worktree(
    repo: Path, origem: Path, tmp_path: Path, marcador: Path
) -> None:
    remotos = tmp_path / "remotos"
    bare = remotos / "acme" / "loja"
    bare.mkdir(parents=True)
    sh("git", "init", "-q", "--bare", "-b", "main", cwd=bare)
    sh("git", "push", "-q", str(bare), "HEAD:refs/heads/main", cwd=origem)
    # credential.helper e url.insteadOf do agente, no worktree
    (repo / ".gitconfig").write_text(
        f'[credential]\n\thelper = !touch {marcador}\n[url "/nada/"]\n\tinsteadOf = {remotos}/\n'
    )
    remoto, area = RemotoGitHub(None, base=str(remotos), dry_run=False), AreaGit()
    assert await remoto.buscar("acme/loja", BRANCH, repo) is False
    await area.garantir_branch(repo, BRANCH)
    (repo / "src" / "b.py").write_text("z")
    await area.commitar(repo, "f1")
    await remoto.enviar("acme/loja", BRANCH, repo)
    assert BRANCH in sh("git", "branch", "--list", cwd=bare) and not marcador.exists()
    outro = await GerenciadorWorktree(tmp_path / "wt2").criar("s2", origem)
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


def test_limpeza_do_tmp_do_teste() -> None:
    assert shutil.which("git")


def _rodar_isolado(codigo: str, prazo_s: float = 15.0) -> subprocess.CompletedProcess[str]:
    """O FIFO trava `os.open` dentro do event loop: só um processo com prazo prova que não trava."""
    return subprocess.run(
        [sys.executable, "-c", codigo], capture_output=True, text=True, timeout=prazo_s
    )


def _tenta(chamada: str) -> str:
    return (
        f"try:\n    asyncio.run({chamada})\nexcept SandboxError:\n"
        "    print('recusou'); sys.exit(0)\nsys.exit(3)\n"
    )


@pytest.mark.parametrize("alvo", ["progress.md", "init.sh", "feature_list.json"])
async def test_fifo_no_lugar_do_arquivo_nao_trava_o_worker_na_leitura_nem_na_escrita(
    repo: Path, alvo: str
) -> None:
    os.mkfifo(repo / alvo)
    cabecalho = (
        "import asyncio, sys\nfrom pathlib import Path\n"
        "from forja.application.portas.sandbox import SandboxError\n"
        "from forja.infrastructure.sandbox.area_git import AreaGit\n"
        f"wt = Path({str(repo)!r})\n"
    )
    ler = cabecalho + _tenta(f"AreaGit().ler(wt, {alvo!r})")
    escrever = cabecalho + _tenta(f"AreaGit().escrever(wt, {alvo!r}, 'x')")
    for codigo in (ler, escrever):
        r = _rodar_isolado(codigo)
        assert r.returncode == 0 and "recusou" in r.stdout, r.stderr


async def test_fifo_no_lugar_do_ponteiro_git_e_recusado_sem_travar(repo: Path) -> None:
    (repo / ".git").unlink()
    os.mkfifo(repo / ".git")
    codigo = (
        "import asyncio, sys\nfrom pathlib import Path\n"
        "from forja.application.portas.sandbox import SandboxError\n"
        "from forja.infrastructure.sandbox.area_git import AreaGit\n"
        f"try:\n    asyncio.run(AreaGit().head(Path({str(repo)!r})))\n"
        "except SandboxError:\n    print('recusou'); sys.exit(0)\nsys.exit(3)\n"
    )
    r = _rodar_isolado(codigo)
    assert r.returncode == 0 and "recusou" in r.stdout, r.stderr


async def test_diretorio_ilegivel_nao_esconde_git_aninhado(repo: Path, tmp_path: Path) -> None:
    sub = repo / "sub"
    sh("git", "init", "-q", str(sub), cwd=tmp_path)
    (sub / "a.py").write_text("x")
    os.chmod(sub, 0o300)  # escrita e travessia, sem listagem: o os.walk comum não vê sub/.git
    try:
        area = AreaGit()
        base = await area.head(repo)
        with pytest.raises(SandboxError, match=r"ilegível|aninhado"):
            await area.mudancas(repo, base)
        with pytest.raises(SandboxError, match=r"ilegível|aninhado"):
            await area.commitar(repo, "m")
        await area.descartar(repo, base)  # devolve as permissões e remove o repositório aninhado
        assert not sub.exists()
    finally:
        if sub.exists():
            os.chmod(sub, 0o700)


async def test_gitlink_que_ja_estava_na_base_e_recusado_pelo_indice(
    origem: Path, tmp_path: Path
) -> None:
    sha = sh("git", "rev-parse", "HEAD", cwd=origem).strip()
    sh("git", "update-index", "--add", "--cacheinfo", f"160000,{sha},sub", cwd=origem)
    sh("git", "commit", "-q", "-m", "gitlink", cwd=origem)
    wt = await GerenciadorWorktree(tmp_path / "wt3").criar("s3", origem)
    area = AreaGit()
    base = await area.head(wt)
    os.chmod(wt / "sub", 0o300) if (wt / "sub").exists() else None
    try:
        with pytest.raises(SandboxError, match="gitlink"):
            await area.mudancas(wt, base)
        with pytest.raises(SandboxError, match="gitlink"):
            await area.commitar(wt, "m")
    finally:
        if (wt / "sub").exists():
            os.chmod(wt / "sub", 0o700)


async def test_git_do_gerenciador_de_worktree_nao_herda_o_ambiente_do_worker(
    origem: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from forja.infrastructure.sandbox.worktree import git_real

    monkeypatch.setenv("FORJA_SEGREDO_DO_WORKER", "valor-secreto")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(origem / "nao-deveria-valer"))
    saida = await git_real("-c", "alias.despejo=!env", "despejo", cwd=origem)
    assert "valor-secreto" not in saida and "FORJA_SEGREDO_DO_WORKER" not in saida
    assert "GIT_CONFIG_GLOBAL=/dev/null" in saida
