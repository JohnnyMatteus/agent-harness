from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import httpx
import jwt

from forja.infrastructure.github.erros import GitHubAuthError

# Permissões mínimas do ADR 0007; o token de instalação é restringido a elas.
PERMISSOES_MINIMAS = {
    "contents": "write",
    "pull_requests": "write",
    "issues": "write",
    "checks": "write",
    "metadata": "read",
}
_JWT_VALIDADE_S = 9 * 60
_MARGEM_EXPIRACAO_S = 120


@dataclass(slots=True)
class _TokenEmCache:
    valor: str
    expira_em: float


class GitHubAppAuth:
    """JWT do App e tokens de instalação de curta duração, reaproveitados até perto de expirar."""

    def __init__(
        self,
        app_id: str,
        chave_privada: str,
        http: httpx.AsyncClient,
        relogio: Callable[[], float] = time.time,
    ) -> None:
        self._app_id = app_id
        self._chave = chave_privada
        self._http = http
        self._relogio = relogio
        self._tokens: dict[str, _TokenEmCache] = {}
        self._instalacoes: dict[str, int] = {}
        self._trava = asyncio.Lock()

    def jwt_do_app(self) -> str:
        agora = int(self._relogio())
        claims = {"iat": agora - 60, "exp": agora + _JWT_VALIDADE_S, "iss": self._app_id}
        try:
            return jwt.encode(claims, self._chave, algorithm="RS256")
        except (ValueError, TypeError, jwt.PyJWTError):
            raise GitHubAuthError("chave privada do GitHub App inválida") from None

    async def token_de_instalacao(self, repositorio: str) -> str:
        async with self._trava:
            em_cache = self._tokens.get(repositorio)
            if em_cache and em_cache.expira_em - self._relogio() > _MARGEM_EXPIRACAO_S:
                return em_cache.valor
            instalacao = await self._instalacao_id(repositorio)
            token = await self._emitir_token(instalacao)
            self._tokens[repositorio] = token
            return token.valor

    async def _instalacao_id(self, repositorio: str) -> int:
        if repositorio not in self._instalacoes:
            resposta = await self._http.get(
                f"/repos/{repositorio}/installation", headers=self._cabecalho_jwt()
            )
            self._exigir_sucesso(resposta, "descobrir a instalação")
            self._instalacoes[repositorio] = int(resposta.json()["id"])
        return self._instalacoes[repositorio]

    async def _emitir_token(self, instalacao: int) -> _TokenEmCache:
        resposta = await self._http.post(
            f"/app/installations/{instalacao}/access_tokens",
            headers=self._cabecalho_jwt(),
            json={"permissions": PERMISSOES_MINIMAS},
        )
        self._exigir_sucesso(resposta, "emitir token de instalação")
        corpo = resposta.json()
        expira = _parse_iso8601(corpo["expires_at"])
        return _TokenEmCache(valor=corpo["token"], expira_em=expira)

    def _cabecalho_jwt(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.jwt_do_app()}",
            "Accept": "application/vnd.github+json",
        }

    @staticmethod
    def _exigir_sucesso(resposta: httpx.Response, operacao: str) -> None:
        if resposta.status_code >= 400:
            raise GitHubAuthError(f"GitHub recusou ao {operacao} (status {resposta.status_code})")


def _parse_iso8601(valor: str) -> float:
    return datetime.fromisoformat(valor.replace("Z", "+00:00")).timestamp()
