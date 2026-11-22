import logging
from collections.abc import Callable
from typing import Any, cast

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from forja.infrastructure.github.app_auth import PERMISSOES_MINIMAS, GitHubAppAuth
from forja.infrastructure.github.chave_privada import VAR_ARQUIVO, VAR_CHAVE, carregar_chave_privada
from forja.infrastructure.github.erros import GitHubAuthError

REPO = "acme-demo/loja-exemplo"
# Um instante antes do expires_at gravado (2026-11-21T13:00:00Z).
AGORA = 1_795_266_000.0 - 3600 + 1800


class Relogio:
    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def montar(chave: str, relogio: Relogio) -> tuple[GitHubAppAuth, httpx.AsyncClient]:
    http = httpx.AsyncClient(base_url="https://api.github.com")
    return GitHubAppAuth("12345", chave, http, relogio), http


def rotas(
    mock: respx.MockRouter, fixture_json: Callable[[str], Any]
) -> tuple[respx.Route, respx.Route]:
    inst = mock.get(f"/repos/{REPO}/installation").respond(
        200, json=fixture_json("api_installation")
    )
    tok = mock.post("/app/installations/777/access_tokens").respond(
        201, json=fixture_json("api_access_token")
    )
    return inst, tok


async def test_token_de_instalacao_e_reaproveitado(
    chave_pem: str, fixture_json: Callable[[str], Any]
) -> None:
    from datetime import datetime

    expira = datetime.fromisoformat(
        fixture_json("api_access_token")["expires_at"].replace("Z", "+00:00")
    ).timestamp()
    relogio = Relogio(expira - 3000)
    auth, http = montar(chave_pem, relogio)
    with respx.mock(base_url="https://api.github.com") as mock:
        _, tok = rotas(mock, fixture_json)

        assert await auth.token_de_instalacao(REPO) == "ghs_TOKEN_FICTICIO_DE_TESTE"
        assert await auth.token_de_instalacao(REPO) == "ghs_TOKEN_FICTICIO_DE_TESTE"
        assert tok.call_count == 1

        relogio.t = expira - 60  # perto de expirar
        await auth.token_de_instalacao(REPO)
        assert tok.call_count == 2
    await http.aclose()


async def test_pede_permissoes_minimas_com_jwt_rs256(
    chave_pem: str, fixture_json: Callable[[str], Any]
) -> None:
    auth, http = montar(chave_pem, Relogio(AGORA))
    with respx.mock(base_url="https://api.github.com") as mock:
        _, tok = rotas(mock, fixture_json)
        await auth.token_de_instalacao(REPO)

        requisicao = tok.calls.last.request
        assert b'"metadata":"read"' in requisicao.content.replace(b" ", b"")
        assert PERMISSOES_MINIMAS["contents"] == "write"
        token = requisicao.headers["authorization"].removeprefix("Bearer ")
        publica = cast(
            RSAPrivateKey, serialization.load_pem_private_key(chave_pem.encode(), None)
        ).public_key()
        claims = jwt.decode(
            token, publica, algorithms=["RS256"], options={"verify_exp": False, "verify_iat": False}
        )
        assert claims["iss"] == "12345"
        assert claims["exp"] - claims["iat"] <= 10 * 60 + 60
    await http.aclose()


async def test_erro_de_auth_nao_vaza_chave_nem_token(
    chave_pem: str, caplog: pytest.LogCaptureFixture
) -> None:
    auth, http = montar(chave_pem, Relogio(AGORA))
    caplog.set_level(logging.DEBUG)
    with respx.mock(base_url="https://api.github.com") as mock:
        mock.get(f"/repos/{REPO}/installation").respond(
            401, json={"message": "Bad credentials ghs_SEGREDO"}
        )
        with pytest.raises(GitHubAuthError) as erro:
            await auth.token_de_instalacao(REPO)
    await http.aclose()

    visivel = str(erro.value) + caplog.text + repr(erro.value)
    assert "PRIVATE KEY" not in visivel
    assert "ghs_SEGREDO" not in visivel
    assert chave_pem.splitlines()[1] not in visivel


async def test_chave_invalida_nao_vaza() -> None:
    auth, http = montar(
        "-----BEGIN PRIVATE KEY-----\nlixo\n-----END PRIVATE KEY-----", Relogio(AGORA)
    )
    with pytest.raises(GitHubAuthError) as erro:
        auth.jwt_do_app()
    await http.aclose()
    assert "lixo" not in str(erro.value)


def test_chave_vem_do_ambiente_ou_de_arquivo(tmp_path: Any) -> None:
    assert carregar_chave_privada({VAR_CHAVE: "linha1\\nlinha2"}) == "linha1\nlinha2"
    arquivo = tmp_path / "app.pem"
    arquivo.write_text("do-arquivo")
    assert (
        carregar_chave_privada({VAR_ARQUIVO: str(arquivo), VAR_CHAVE: "ignorada"}) == "do-arquivo"
    )
    with pytest.raises(GitHubAuthError):
        carregar_chave_privada({})
