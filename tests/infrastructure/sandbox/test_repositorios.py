from pathlib import Path

import pytest

from forja.application.portas.sandbox import SandboxError
from forja.infrastructure.sandbox.repositorios import RepositoriosLocais


def test_resolve_so_dentro_da_raiz(tmp_path: Path) -> None:
    (tmp_path / "raiz" / "a" / "b" / ".git").mkdir(parents=True)
    repos = RepositoriosLocais(tmp_path / "raiz")
    assert repos.caminho("a/b").endswith("raiz/a/b")
    for ruim in ("../x", "a/..", "a/c", "a/b/c"):
        with pytest.raises(SandboxError):
            repos.caminho(ruim)


def test_symlink_para_fora_e_recusado(tmp_path: Path) -> None:
    fora = tmp_path / "fora"
    (fora / ".git").mkdir(parents=True)
    (tmp_path / "raiz" / "a").mkdir(parents=True)
    (tmp_path / "raiz" / "a" / "b").symlink_to(fora)
    with pytest.raises(SandboxError):
        RepositoriosLocais(tmp_path / "raiz").caminho("a/b")
