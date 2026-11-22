"""Execução real (Docker + git); roda só no CI: `pytest -m integration`.

Pré-requisitos do job (criados por `infra/sandbox/preparar.sh`): imagem `forja-sandbox:latest`,
rede `forja-sandbox-net` (--internal) e o proxy Squid `forja-egress-proxy`
(infra/sandbox/squid.conf).
"""

import subprocess
from pathlib import Path

import pytest

from forja.application.portas.sandbox import EspecSandbox
from forja.infrastructure.sandbox.docker import DockerSandbox
from forja.infrastructure.sandbox.worktree import GerenciadorWorktree

pytestmark = pytest.mark.integration


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    for cmd in (
        ["git", "init", "-q"],
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "i",
        ],
    ):
        subprocess.run(cmd, cwd=r, check=True)
    return r


async def test_ciclo_sem_root_e_arquivos_restritos(repo: Path, tmp_path: Path):
    sb = DockerSandbox(GerenciadorWorktree(tmp_path / "wt"))
    ativo = await sb.criar(EspecSandbox("it1", str(repo)))
    try:
        assert (await ativo.executar(["id", "-u"])).stdout.strip() != "0"
        assert (await ativo.executar(["touch", "/etc/x"])).codigo_saida != 0
        assert (await ativo.executar(["touch", "ok.txt"])).codigo_saida == 0
        # Direto, sem proxy: a rede interna não tem rota externa.
        direto = await ativo.executar(
            [
                "python",
                "-c",
                "import urllib.request as u;"
                "u.build_opener(u.ProxyHandler({})).open('http://example.com',timeout=5)",
            ]
        )
        assert direto.codigo_saida != 0
        # Pelo proxy: ele tem de estar de pé e recusar o que está fora da allowlist (403),
        # senão a falha acima poderia ser só "proxy ausente".
        via_proxy = await ativo.executar(
            [
                "python",
                "-c",
                "import urllib.request as u,urllib.error as e,sys\n"
                "try: u.urlopen('http://example.com',timeout=10)\n"
                "except e.HTTPError as x: sys.exit(0 if x.code == 403 else 2)\n"
                "sys.exit(3)",
            ]
        )
        assert via_proxy.codigo_saida == 0, via_proxy.stderr
    finally:
        await sb.destruir("it1")
    assert not ativo.worktree.exists()


async def test_agente_nao_alcanca_a_api_do_github(repo: Path, tmp_path: Path):
    """Só o workflow escreve no GitHub (ADR 0007): do sandbox, api.github.com é recusado."""
    sb = DockerSandbox(GerenciadorWorktree(tmp_path / "wt"))
    ativo = await sb.criar(EspecSandbox("it2", str(repo)))
    try:
        res = await ativo.executar(
            [
                "python",
                "-c",
                "import urllib.request as u,urllib.error as e,sys\n"
                "try: u.urlopen('http://api.github.com',timeout=10)\n"
                "except e.HTTPError as x: sys.exit(0 if x.code == 403 else 2)\n"
                "sys.exit(3)",
            ]
        )
        assert res.codigo_saida == 0, res.stderr
    finally:
        await sb.destruir("it2")
