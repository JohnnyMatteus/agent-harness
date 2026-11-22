"""Git worktree por sessão, sempre fora do diretório do repositório de origem."""

from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
from pathlib import Path
from typing import Protocol

from forja.application.portas.sandbox import SandboxError


class GitRunner(Protocol):
    async def __call__(self, *args: str, cwd: Path | None = None) -> str: ...


async def git_real(*args: str, cwd: Path | None = None) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise SandboxError(f"git {args[0]} falhou: {err.decode().strip()}")
    return out.decode()


def caminho_do_registro(worktree: Path) -> Path:
    """Registro fora do worktree (o container só enxerga o worktree): `<raiz>/.meta/<nome>.json`."""
    return worktree.parent / ".meta" / f"{worktree.name}.json"


def registrar_gitdir(worktree: Path, gitdir: Path, ponteiro: str) -> None:
    registro = caminho_do_registro(worktree)
    registro.parent.mkdir(parents=True, exist_ok=True)
    registro.write_text(json.dumps({"gitdir": str(gitdir), "ponteiro": ponteiro}))


def gitdir_registrado(worktree: Path) -> tuple[Path, str]:
    """(gitdir confiável, conteúdo esperado do ponteiro `.git`), resolvidos na criação.
    Sem registro, falha fechada."""
    try:
        dados = json.loads(caminho_do_registro(worktree).read_text())
        return Path(str(dados["gitdir"])), str(dados["ponteiro"])
    except (OSError, ValueError, KeyError):
        raise SandboxError("worktree sem gitdir registrado na criação") from None


class GerenciadorWorktree:
    def __init__(self, raiz: Path, git: GitRunner = git_real) -> None:
        self._raiz = raiz
        self._git = git

    def caminho(self, sessao_id: str) -> Path:
        if not sessao_id.replace("-", "").replace("_", "").isalnum():
            raise SandboxError(f"sessao_id inválido: {sessao_id!r}")
        return self._raiz / sessao_id

    async def criar(self, sessao_id: str, repo: Path, ref: str = "HEAD") -> Path:
        destino = self.caminho(sessao_id)
        self._raiz.mkdir(parents=True, exist_ok=True)
        await self._git("worktree", "add", "--detach", str(destino), ref, cwd=repo)
        self._registrar(destino, repo)
        return destino

    @staticmethod
    def _registrar(destino: Path, repo: Path) -> None:
        """Resolve o gitdir agora, antes de qualquer processo do container existir."""
        ponteiro = (destino / ".git").read_text().strip()
        if not ponteiro.startswith("gitdir: "):
            raise SandboxError("ponteiro .git inesperado no worktree recém-criado")
        gitdir = Path(ponteiro.removeprefix("gitdir: ")).resolve()
        administrativo = (repo / ".git" / "worktrees").resolve()
        if not gitdir.is_relative_to(administrativo):
            raise SandboxError("gitdir do worktree fora da área administrativa do clone")
        registrar_gitdir(destino, gitdir, ponteiro)

    async def remover(self, sessao_id: str, repo: Path) -> None:
        destino = self.caminho(sessao_id)
        with contextlib.suppress(SandboxError):  # já removido: destruir é idempotente
            await self._git("worktree", "remove", "--force", str(destino), cwd=repo)
        shutil.rmtree(destino, ignore_errors=True)
        caminho_do_registro(destino).unlink(missing_ok=True)
        await self._git("worktree", "prune", cwd=repo)
