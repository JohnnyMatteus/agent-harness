from __future__ import annotations

import base64
import re
import unicodedata
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from forja.application.portas.revisao import EstadoDosChecks
from forja.domain.artefatos import TETO_DE_ARTEFATO, ArtefatoInvalido, caminho_relativo_seguro
from forja.domain.politica import Politica, PoliticaInvalida
from forja.domain.revisao import ArquivoDoDiff, DiffDaEntrega
from forja.infrastructure.github.erros import BranchProtegida, GitHubApiError
from forja.infrastructure.yaml_estrito import YamlInvalido
from forja.infrastructure.yaml_estrito import ler as ler_yaml

PREFIXO_BRANCH = "forja/"
TETO_DE_PATCH = 8_000
_PR_PRONTO = (
    "mutation($id: ID!) { markPullRequestReadyForReview(input: {pullRequestId: $id}) "
    "{ clientMutationId } }"
)
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

    # --- revisão e deploy -------------------------------------------------------------

    async def diff_da_entrega(self, repositorio: str, branch: str) -> DiffDaEntrega:
        padrao = (await self._chamar("GET", repositorio, f"/repos/{repositorio}"))["default_branch"]
        comparacao = await self._chamar(
            "GET", repositorio, f"/repos/{repositorio}/compare/{quote(padrao)}...{quote(branch)}"
        )
        arquivos: list[ArquivoDoDiff] = []
        for f in comparacao.get("files", [])[:300]:
            arquivos.append(
                ArquivoDoDiff(
                    f["filename"],
                    str(f.get("status", "modified")),
                    int(f.get("additions", 0)),
                    int(f.get("deletions", 0)),
                    str(f.get("patch", ""))[:TETO_DE_PATCH],
                )
            )
        sha = str(comparacao.get("commits", [{}])[-1].get("sha", ""))
        return DiffDaEntrega(tuple(arquivos), sha)

    async def branch_padrao(self, repositorio: str) -> str:
        return str(
            (await self._chamar("GET", repositorio, f"/repos/{repositorio}"))["default_branch"]
        )

    async def politica(self, repositorio: str) -> Politica:
        padrao = (await self._chamar("GET", repositorio, f"/repos/{repositorio}"))["default_branch"]
        texto = await self.ler_arquivo(repositorio, padrao, ".forja/policy.yaml")
        if texto is None:
            return Politica.padrao_fechado()
        try:
            return Politica.de_dict(ler_yaml(texto))
        except (YamlInvalido, PoliticaInvalida):
            return Politica.padrao_fechado()  # política ilegível: fecha, não abre

    async def estado_dos_checks(self, repositorio: str, sha: str) -> EstadoDosChecks:
        dados = await self._chamar(
            "GET", repositorio, f"/repos/{repositorio}/commits/{sha}/check-runs?per_page=100"
        )
        runs = dados.get("check_runs", [])
        if any(
            r.get("conclusion") in ("failure", "cancelled", "timed_out", "action_required")
            for r in runs
        ):
            return "falhou"
        if not runs or any(r.get("status") != "completed" for r in runs):
            return "pendente"
        return "verde"

    async def numero_do_pr(self, repositorio: str, branch: str) -> int | None:
        dono = repositorio.split("/")[0]
        abertos = await self._chamar(
            "GET", repositorio, f"/repos/{repositorio}/pulls?head={quote(dono)}:{quote(branch)}"
        )
        return int(abertos[0]["number"]) if abertos else None

    async def criar_check_run(
        self, repositorio: str, head_sha: str, nome: str, conclusao: str, titulo: str,
        resumo: str, anotacoes: list[dict[str, Any]],
    ) -> None:  # fmt: skip
        await self._chamar(
            "POST",
            repositorio,
            f"/repos/{repositorio}/check-runs",
            {
                "name": nome[:80],
                "head_sha": head_sha,
                "status": "completed",
                "conclusion": conclusao,
                "output": {
                    "title": titulo[:120],
                    "summary": resumo[:60_000],
                    "annotations": anotacoes[:50],
                },
            },
        )

    async def marcar_pr_pronto(self, repositorio: str, numero: int) -> None:
        pr = await self._chamar("GET", repositorio, f"/repos/{repositorio}/pulls/{numero}")
        resposta = await self._chamar(
            "POST",
            repositorio,
            "/graphql",
            {"query": _PR_PRONTO, "variables": {"id": pr["node_id"]}},
        )
        if resposta.get("errors"):  # o GraphQL devolve 200 com `errors`: não é sucesso
            raise GitHubApiError(200, "graphql markPullRequestReadyForReview")

    async def mesclar_pr(self, repositorio: str, numero: int, sha: str) -> None:
        resposta = await self._chamar(
            "PUT",
            repositorio,
            f"/repos/{repositorio}/pulls/{numero}/merge",
            {"sha": sha, "merge_method": "squash"},
        )
        if resposta.get("merged") is not True:  # só `merged: true` é merge feito
            raise GitHubApiError(200, "merge não confirmado")

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
