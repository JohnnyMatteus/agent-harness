"""Fetch e push da branch da entrega. É o único lugar onde o worker usa credencial de git.

O token vai por variável de ambiente (`GIT_CONFIG_*`), nunca em argumento nem em URL, e o
cabeçalho só vale para o host configurado. Push só de `forja/*`, refspec explícito, sem force.
Não foi exercitado contra o GitHub real; os testes usam um repositório bare local.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Protocol

from forja.application.portas.sandbox import SandboxError
from forja.domain.seguranca import repositorio_valido
from forja.infrastructure.github.cliente import PREFIXO_BRANCH
from forja.infrastructure.sandbox.area_git import git


class ProvedorDeToken(Protocol):
    async def token_de_instalacao(self, repositorio: str) -> str: ...


def _branch_valida(branch: str) -> str:
    resto = branch.removeprefix(PREFIXO_BRANCH)
    if (
        not branch.startswith(PREFIXO_BRANCH)
        or not resto
        or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in resto)
    ):
        raise SandboxError(f"branch recusada: {branch[:60]!r}")
    return branch


class RemotoGitHub:
    def __init__(
        self, auth: ProvedorDeToken | None, base: str = "https://github.com", dry_run: bool = True
    ) -> None:
        self._auth = auth
        self._base = base.rstrip("/")
        self._dry_run = dry_run

    def _url(self, repositorio: str) -> str:
        if not repositorio_valido(repositorio):
            raise SandboxError("repositório inválido")
        sufixo = "" if self._base.startswith("/") else ".git"
        return f"{self._base}/{repositorio}{sufixo}"

    async def _ambiente(self, repositorio: str) -> dict[str, str]:
        if self._auth is None or self._base.startswith("/"):
            return {}
        token = await self._auth.token_de_instalacao(repositorio)
        basico = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        return {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"http.{self._base}/.extraheader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basico}",
        }

    async def buscar(self, repositorio: str, branch: str, worktree: Path) -> bool:
        branch = _branch_valida(branch)
        if self._dry_run:
            return False
        url = self._url(repositorio)
        try:
            await git(
                worktree, "fetch", "-q", "--no-tags", "--depth=50", url, f"+refs/heads/{branch}",
                ambiente=await self._ambiente(repositorio),
            )  # fmt: skip
        except SandboxError as erro:
            if "couldn't find remote ref" in str(erro):
                return False
            raise
        await git(worktree, "checkout", "-q", "-B", branch, "FETCH_HEAD")
        return True

    async def enviar(self, repositorio: str, branch: str, worktree: Path) -> None:
        branch = _branch_valida(branch)
        if self._dry_run:
            return
        await git(
            worktree, "push", "-q", self._url(repositorio), f"HEAD:refs/heads/{branch}",
            ambiente=await self._ambiente(repositorio),
        )  # fmt: skip
