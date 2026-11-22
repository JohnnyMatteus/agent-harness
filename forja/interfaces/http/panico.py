from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from forja.application.casos_de_uso.acionar_panico import AcionarPanico

log = logging.getLogger(__name__)
router = APIRouter()


@dataclass(frozen=True, slots=True)
class DependenciasPanico:
    token_sha256: str
    acionar: AcionarPanico


def dependencias(request: Request) -> DependenciasPanico:
    return request.app.state.panico


def _autenticado(autorizacao: str | None, esperado_sha256: str) -> bool:
    """ADR 0019: bearer de alta entropia; só o hash fica na configuração."""
    esquema, _, token = (autorizacao or "").partition(" ")
    if esquema.lower() != "bearer" or not token or not esperado_sha256:
        return False
    return hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), esperado_sha256.lower())


@router.post("/panico")
async def acionar_panico(
    deps: Annotated[DependenciasPanico, Depends(dependencias)],
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, int]:
    if not _autenticado(authorization, deps.token_sha256):
        log.warning("tentativa de acionar o pânico sem credencial válida")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Bearer"})
    return {"cancelados": await deps.acionar.executar()}
