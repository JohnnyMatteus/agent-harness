from collections.abc import Callable
from typing import Any

import httpx
import pytest
import respx

from forja.infrastructure.github.cliente import (
    GitHubCliente,
    garantir_branch_de_trabalho,
    nome_da_branch,
)
from forja.infrastructure.github.erros import BranchProtegida

REPO = "acme-demo/loja-exemplo"


class AuthFalso:
    async def token_de_instalacao(self, repositorio: str) -> str:
        return "ghs_TOKEN_FICTICIO_DE_TESTE"


def test_nome_da_branch() -> None:
    assert nome_da_branch("abc", "corrige-login") == "forja/abc-corrige-login"
    assert nome_da_branch("abc", "Corrige o Login!") == "forja/abc-corrige-o-login"


def test_branch_padrao_ou_fora_do_prefixo_e_recusada() -> None:
    with pytest.raises(BranchProtegida):
        garantir_branch_de_trabalho("main", "main")
    with pytest.raises(BranchProtegida):
        garantir_branch_de_trabalho("release", "main")
    garantir_branch_de_trabalho("forja/abc-x", "main")


async def test_comenta_com_token_de_instalacao(fixture_json: Callable[[str], Any]) -> None:
    async with httpx.AsyncClient(base_url="https://api.github.com") as http:
        cliente = GitHubCliente(AuthFalso(), http)
        with respx.mock(base_url="https://api.github.com") as mock:
            rota = mock.post(f"/repos/{REPO}/issues/42/comments").respond(
                201, json=fixture_json("api_comment_created")
            )
            await cliente.comentar_issue(REPO, 42, "ok")

            assert (
                rota.calls.last.request.headers["authorization"]
                == "Bearer ghs_TOKEN_FICTICIO_DE_TESTE"
            )


async def test_cria_branch_a_partir_da_padrao(fixture_json: Callable[[str], Any]) -> None:
    async with httpx.AsyncClient(base_url="https://api.github.com") as http:
        cliente = GitHubCliente(AuthFalso(), http)
        with respx.mock(base_url="https://api.github.com") as mock:
            mock.get(f"/repos/{REPO}").respond(200, json=fixture_json("api_repo"))
            mock.get(f"/repos/{REPO}/git/ref/heads/main").respond(
                200, json=fixture_json("api_ref_main")
            )
            criar = mock.post(f"/repos/{REPO}/git/refs").respond(201, json={})

            assert (
                await cliente.criar_branch(REPO, "abc", "corrige-login")
                == "forja/abc-corrige-login"
            )
            corpo = criar.calls.last.request.content
            assert b"refs/heads/forja/abc-corrige-login" in corpo
            assert b"a1b2c3d4e5f60718293a4b5c6d7e8f9012345678" in corpo


async def test_recusa_branch_padrao_antes_de_escrever(fixture_json: Callable[[str], Any]) -> None:
    repo_padrao_forja = {**fixture_json("api_repo"), "default_branch": "forja/abc-x"}
    async with httpx.AsyncClient(base_url="https://api.github.com") as http:
        cliente = GitHubCliente(AuthFalso(), http)
        with respx.mock(base_url="https://api.github.com", assert_all_called=False) as mock:
            mock.get(f"/repos/{REPO}").respond(200, json=repo_padrao_forja)
            criar = mock.post(f"/repos/{REPO}/git/refs").respond(201, json={})

            with pytest.raises(BranchProtegida):
                await cliente.criar_branch(REPO, "abc", "x")
            assert criar.call_count == 0


async def test_permissao_de_escrita(fixture_json: Callable[[str], Any]) -> None:
    async with httpx.AsyncClient(base_url="https://api.github.com") as http:
        cliente = GitHubCliente(AuthFalso(), http)
        with respx.mock(base_url="https://api.github.com") as mock:
            mock.get(f"/repos/{REPO}/collaborators/maria-dev/permission").respond(
                200, json=fixture_json("api_permission_write")
            )
            mock.get(f"/repos/{REPO}/collaborators/leitor/permission").respond(
                200, json=fixture_json("api_permission_read")
            )
            mock.get(f"/repos/{REPO}/collaborators/estranho/permission").respond(404, json={})

            assert await cliente.tem_escrita(REPO, "maria-dev")
            assert not await cliente.tem_escrita(REPO, "leitor")
            assert not await cliente.tem_escrita(REPO, "estranho")


async def test_leitura_de_arquivo_distingue_ausencia_erro_e_tamanho_absurdo() -> None:
    import base64

    from forja.domain.artefatos import TETO_DE_ARTEFATO, ArtefatoInvalido
    from forja.infrastructure.github.erros import GitHubApiError

    url = f"/repos/{REPO}/contents/.forja/x/spec.md"
    async with httpx.AsyncClient(base_url="https://api.github.com") as http:
        cliente = GitHubCliente(AuthFalso(), http)
        with respx.mock(base_url="https://api.github.com") as mock:
            rota = mock.get(url)
            rota.respond(404)
            assert await cliente.ler_arquivo(REPO, "forja/x", ".forja/x/spec.md") is None
            rota.respond(500)
            with pytest.raises(GitHubApiError):
                await cliente.ler_arquivo(REPO, "forja/x", ".forja/x/spec.md")
            grande = base64.b64encode(b"a" * (TETO_DE_ARTEFATO + 1)).decode()
            rota.respond(200, json={"content": grande, "sha": "s", "size": TETO_DE_ARTEFATO + 1})
            with pytest.raises(ArtefatoInvalido):
                await cliente.ler_arquivo(REPO, "forja/x", ".forja/x/spec.md")
            ok = base64.b64encode(b"oi").decode()
            rota.respond(200, json={"content": ok, "sha": "s", "size": 2})
            assert await cliente.ler_arquivo(REPO, "forja/x", ".forja/x/spec.md") == "oi"
