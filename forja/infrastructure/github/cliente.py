from __future__ import annotations

import re
import unicodedata
from typing import Any, Protocol

import httpx

from forja.infrastructure.github.erros import BranchProtegida, GitHubApiError

PREFIXO_BRANCH = "forja/"
_PERMISSOES_ESCRITA = {"admin", "maintain", "write"}


def nome_da_branch(intent_id: str, slug: str) -> str:
    return f"{PREFIXO_BRANCH}{intent_id}-{_slugificar(slug)}"


def _slugificar(texto: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")[:50] or "intent"


def garantir_branch_de_trabalho(branch: str, branch_padrao: str) -> None:
    """Recusa antes de qualquer chamada de escrita (ADR 0007)."""
    if branch == branch_padrao or not branch.startswith(PREFIXO_BRANCH):
        raise BranchProtegida(f"escrita recusada na branch {branch!r}")


class ProvedorDeToken(Protocol):
    async def token_de_instalacao(self, repositorio: str) -> str: ...


class GitHubCliente:
    """Implementa `GitHubPort` e `VerificadorPermissao` sobre a API REST, sempre com token de instalação."""

    def __init__(self, auth: ProvedorDeToken, http: httpx.AsyncClient) -> None:
        self._auth = auth
        self._http = http

    async def comentar_issue(self, repositorio: str, numero: int, corpo: str) -> None:
        await self._chamar("POST", repositorio, f"/repos/{repositorio}/issues/{numero}/comments", {"body": corpo})

    async def criar_branch(self, repositorio: str, intent_id: str, slug: str) -> str:
        nome = nome_da_branch(intent_id, slug)
        padrao = (await self._chamar("GET", repositorio, f"/repos/{repositorio}"))["default_branch"]
        garantir_branch_de_trabalho(nome, padrao)
        ref = await self._chamar("GET", repositorio, f"/repos/{repositorio}/git/ref/heads/{padrao}")
        await self._chamar(
            "POST",
            repositorio,
            f"/repos/{repositorio}/git/refs",
            {"ref": f"refs/heads/{nome}", "sha": ref["object"]["sha"]},
        )
        return nome

    async def tem_escrita(self, repositorio: str, usuario: str) -> bool:
        try:
            dados = await self._chamar("GET", repositorio, f"/repos/{repositorio}/collaborators/{usuario}/permission")
        except GitHubApiError as erro:
            if erro.status == 404:
                return False
            raise
        return dados.get("permission") in _PERMISSOES_ESCRITA

    async def _chamar(self, metodo: str, repositorio: str, caminho: str, json: dict[str, Any] | None = None) -> Any:
        token = await self._auth.token_de_instalacao(repositorio)
        resposta = await self._http.request(
            metodo,
            caminho,
            json=json,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        )
        if resposta.status_code >= 400:
            raise GitHubApiError(resposta.status_code, f"{metodo} {caminho.split('/')[1]}")
        return resposta.json()
