"""Git worktree por sessão, sempre fora do diretório do repositório de origem."""

from __future__ import annotations

import asyncio
import contextlib
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
        return destino

    async def remover(self, sessao_id: str, repo: Path) -> None:
        destino = self.caminho(sessao_id)
        with contextlib.suppress(SandboxError):  # já removido: destruir é idempotente
            await self._git("worktree", "remove", "--force", str(destino), cwd=repo)
        shutil.rmtree(destino, ignore_errors=True)
        await self._git("worktree", "prune", cwd=repo)
