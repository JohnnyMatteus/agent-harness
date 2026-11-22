from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from forja.application.casos_de_uso.ativar_entrega import AtivarEntrega
from forja.application.portas.deduplicacao import RegistroEntregas
from forja.infrastructure.github.assinatura import assinatura_valida
from forja.infrastructure.github.tradutores import traduzir
from forja.infrastructure.telemetry.metricas import MetricasForja
from forja.infrastructure.telemetry.otel import tracer

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ConfigWebhook:
    segredo: str
    max_corpo_bytes: int


@dataclass(frozen=True, slots=True)
class DependenciasWebhook:
    config: ConfigWebhook
    registro: RegistroEntregas
    ativar: AtivarEntrega
    metricas: MetricasForja | None = None


def dependencias(request: Request) -> DependenciasWebhook:
    return request.app.state.webhook


router = APIRouter()


async def _ler_corpo(request: Request, limite: int) -> bytes:
    declarado = request.headers.get("content-length")
    if declarado and declarado.isdigit() and int(declarado) > limite:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE)
    corpo = bytearray()
    async for pedaco in request.stream():
        corpo.extend(pedaco)
        if len(corpo) > limite:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE)
    return bytes(corpo)


@router.post("/webhooks/github", status_code=status.HTTP_202_ACCEPTED)
async def receber_webhook(
    request: Request,
    deps: Annotated[DependenciasWebhook, Depends(dependencias)],
    x_hub_signature_256: Annotated[str | None, Header()] = None,
    x_github_event: Annotated[str | None, Header()] = None,
    x_github_delivery: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    corpo = await _ler_corpo(request, deps.config.max_corpo_bytes)
    if not assinatura_valida(deps.config.segredo, corpo, x_hub_signature_256):
        log.warning("assinatura de webhook inválida", extra={"entrega": x_github_delivery})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "assinatura inválida")
    if not x_github_delivery or not x_github_event:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "faltam X-GitHub-Event ou X-GitHub-Delivery"
        )
    payload = _decodificar(corpo)

    if not await deps.registro.registrar_nova(x_github_delivery):
        return {"status": "duplicada"}
    try:
        with tracer().start_as_current_span("gateway.webhook") as span:
            span.set_attribute("forja.evento", x_github_event[:40])
            resultado = await deps.ativar.executar(traduzir(x_github_event, payload))
            span.set_attribute("forja.resultado", resultado)
    except Exception:
        # Libera o id para o reenvio do GitHub não ser descartado como duplicata.
        await deps.registro.esquecer(x_github_delivery)
        log.exception("falha ao processar webhook", extra={"entrega": x_github_delivery})
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "falha ao processar") from None
    if resultado == "iniciada" and deps.metricas is not None:
        deps.metricas.iniciadas.inc()
    return {"status": resultado}


def _decodificar(corpo: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(corpo)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "JSON inválido") from None
    if not isinstance(payload, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "payload deve ser um objeto JSON")
    return cast("dict[str, Any]", payload)
