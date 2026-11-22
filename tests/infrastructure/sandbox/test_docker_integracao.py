"""Execução real (Docker + git); roda só no CI: `pytest -m integration`.

Pré-requisitos do job: imagem `forja-sandbox:latest` (infra/sandbox/Dockerfile) e a rede
`forja-sandbox-net` (--internal) com o proxy Squid `forja-egress-proxy` (infra/sandbox/squid.conf).
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
        assert (
            await ativo.executar(
                [
                    "python",
                    "-c",
                    "import urllib.request as u;u.urlopen('http://example.com',timeout=5)",
                ]
            )
        ).codigo_saida != 0
    finally:
        await sb.destruir("it1")
    assert not ativo.worktree.exists()
