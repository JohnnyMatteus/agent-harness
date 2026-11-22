from __future__ import annotations

from fastapi import FastAPI

from forja.interfaces.http import panico, webhooks


def criar_app(
    webhook: webhooks.DependenciasWebhook, acionar_panico: panico.DependenciasPanico
) -> FastAPI:
    app = FastAPI(title="Forja", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.webhook = webhook
    app.state.panico = acionar_panico
    app.include_router(webhooks.router)
    app.include_router(panico.router)
    return app
