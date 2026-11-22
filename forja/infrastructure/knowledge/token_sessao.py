"""Token de sessão do knowledge: o escopo (organização e repositório) vem assinado, nunca do modelo.

Quem emite é o workflow ao abrir a sessão do agente; o servidor MCP só verifica.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt

from forja.domain.erros import ErroDeDominio
from forja.domain.knowledge import Escopo

_ALGORITMO = "HS256"
_AUDIENCIA = "forja-knowledge"
SEGREDO_MINIMO = 32


class TokenInvalido(Exception):
    """Token ausente, adulterado, expirado ou com escopo inválido."""


def _segredo(segredo: str) -> bytes:
    if len(segredo.encode()) < SEGREDO_MINIMO:
        raise ValueError(f"segredo do token precisa de ao menos {SEGREDO_MINIMO} bytes")
    return segredo.encode()


def emitir_token(
    escopo: Escopo,
    sessao: str,
    segredo: str,
    *,
    validade: timedelta = timedelta(hours=2),
    agora: datetime | None = None,
) -> str:
    instante = agora or datetime.now(UTC)
    return jwt.encode(
        {
            "sub": sessao,
            "aud": _AUDIENCIA,
            "org": escopo.organizacao,
            "repo": escopo.repositorio,
            "iat": instante,
            "exp": instante + validade,
        },
        _segredo(segredo),
        algorithm=_ALGORITMO,
    )


def verificar_token(token: str, segredo: str) -> Escopo:
    try:
        claims = jwt.decode(
            token,
            _segredo(segredo),
            algorithms=[_ALGORITMO],
            audience=_AUDIENCIA,
            options={"require": ["exp", "sub", "aud", "org", "repo"]},
        )
        return Escopo(str(claims["org"]), str(claims["repo"]))
    except (jwt.PyJWTError, ErroDeDominio) as erro:
        raise TokenInvalido("token de sessao invalido") from erro
