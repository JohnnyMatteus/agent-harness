from __future__ import annotations

import base64
import re
import unicodedata
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from forja.domain.artefatos import TETO_DE_ARTEFATO, ArtefatoInvalido, caminho_relativo_seguro
from forja.infrastructure.github.erros import BranchProtegida, GitHubApiError

PREFIXO_BRANCH = "forja/"
_PERMISSOES_ESCRITA = {"admin", "maintain", "write"}


def nome_da_branch(intent_id: str, slug: str) -> str:
    return f"{PREFIXO_BRANCH}{intent_id}-{slugificar(slug)}"


def slugificar(texto: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")[:50] or "intent"


def garantir_branch_de_trabalho(branch: str, branch_padrao: str) -> None:
    """Recusa antes de qualquer chamada de escrita (ADR 0007)."""
    if branch == branch_padrao or not branch.startswith(PREFIXO_BRANCH):
        raise BranchProtegida(f"escrita recusada na branch {branch!r}")


class ProvedorDeToken(Protocol):
    async def token_de_instalacao(self, repositorio: str) -> str: ...


class GitHubCliente:
    """Implementa `GitHubPort` e `VerificadorPermissao` na API REST, com token de instalação."""

    def __init__(self, auth: ProvedorDeToken, http: httpx.AsyncClient) -> None:
        self._auth = auth
        self._http = http

    async def comentar_issue(self, repositorio: str, numero: int, corpo: str) -> None:
        await self._chamar(
            "POST", repositorio, f"/repos/{repositorio}/issues/{numero}/comments", {"body": corpo}
        )

    async def criar_branch(self, repositorio: str, intent_id: str, slug: str) -> str:
        nome = nome_da_branch(intent_id, slug)
        padrao = (await self._chamar("GET", repositorio, f"/repos/{repositorio}"))["default_branch"]
        garantir_branch_de_trabalho(nome, padrao)
        ref = await self._chamar("GET", repositorio, f"/repos/{repositorio}/git/ref/heads/{padrao}")
        try:
            await self._chamar(
                "POST",
                repositorio,
                f"/repos/{repositorio}/git/refs",
                {"ref": f"refs/heads/{nome}", "sha": ref["object"]["sha"]},
            )
        except GitHubApiError as erro:
            if erro.status != 422:  # 422: a branch já existe (retentativa); é o desejado
                raise
        return nome

    async def commitar_arquivo(
        self, repositorio: str, branch: str, caminho: str, conteudo: str, mensagem: str
    ) -> bool:
        if not branch.startswith(PREFIXO_BRANCH):
            raise BranchProtegida(f"escrita recusada na branch {branch!r}")
        caminho = caminho_relativo_seguro(caminho)
        url = f"/repos/{repositorio}/contents/{quote(caminho)}"
        existente = await self._conteudo(repositorio, url, branch)
        if existente is not None and existente[0] == conteudo:
            return False
        corpo: dict[str, Any] = {
            "message": mensagem,
            "content": base64.b64encode(conteudo.encode()).decode(),
            "branch": branch,
        }
        if existente is not None:
            corpo["sha"] = existente[1]
        await self._chamar("PUT", repositorio, url, corpo)
        return True

    async def ler_arquivo(self, repositorio: str, branch: str, caminho: str) -> str | None:
        caminho = caminho_relativo_seguro(caminho)
        achado = await self._conteudo(
            repositorio, f"/repos/{repositorio}/contents/{quote(caminho)}", branch
        )
        return None if achado is None else achado[0]

    async def abrir_pr(
        self, repositorio: str, branch: str, titulo: str, corpo: str, rascunho: bool
    ) -> str:
        if not branch.startswith(PREFIXO_BRANCH):
            raise BranchProtegida(f"PR recusado para a branch {branch!r}")
        dono = repositorio.split("/")[0]
        abertos = await self._chamar(
            "GET", repositorio, f"/repos/{repositorio}/pulls?head={quote(dono)}:{quote(branch)}"
        )
        if abertos:
            return str(abertos[0]["html_url"])
        padrao = (await self._chamar("GET", repositorio, f"/repos/{repositorio}"))["default_branch"]
        pr = await self._chamar(
            "POST",
            repositorio,
            f"/repos/{repositorio}/pulls",
            {"title": titulo, "head": branch, "base": padrao, "body": corpo, "draft": rascunho},
        )
        return str(pr["html_url"])

    async def _conteudo(self, repositorio: str, url: str, ref: str) -> tuple[str, str] | None:
        try:
            dados = await self._chamar("GET", repositorio, f"{url}?ref={quote(ref)}")
        except GitHubApiError as erro:
            if erro.status == 404:
                return None
            raise
        if (
            int(dados.get("size", 0)) > TETO_DE_ARTEFATO
            or len(str(dados["content"])) > TETO_DE_ARTEFATO * 2
        ):
            raise ArtefatoInvalido("arquivo acima do teto de tamanho de artefato")
        texto = base64.b64decode(dados["content"]).decode(errors="replace")
        if len(texto) > TETO_DE_ARTEFATO:
            raise ArtefatoInvalido("arquivo acima do teto de tamanho de artefato")
        return texto, str(dados["sha"])

    async def tem_escrita(self, repositorio: str, usuario: str) -> bool:
        try:
            dados = await self._chamar(
                "GET", repositorio, f"/repos/{repositorio}/collaborators/{usuario}/permission"
            )
        except GitHubApiError as erro:
            if erro.status == 404:
                return False
            raise
        return dados.get("permission") in _PERMISSOES_ESCRITA

    async def _chamar(
        self, metodo: str, repositorio: str, caminho: str, json: dict[str, Any] | None = None
    ) -> Any:
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
