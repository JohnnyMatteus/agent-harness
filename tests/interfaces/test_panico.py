import hashlib
from typing import Any

import httpx
import pytest

from forja.application.casos_de_uso.acionar_panico import AcionarPanico
from forja.application.portas.entregas import ResultadoInicio
from forja.interfaces.http.app import criar_app
from forja.interfaces.http.panico import DependenciasPanico
from forja.interfaces.http.webhooks import ConfigWebhook, DependenciasWebhook

TOKEN = "token-de-teste-com-bastante-entropia"


class Entregas:
    async def iniciar(self, *_: Any, **__: Any) -> ResultadoInicio:
        return "iniciada"

    async def parar(self, *_: Any, **__: Any) -> bool:
        return True

    async def cancelar_todas(self) -> int:
        return 4


def cliente() -> httpx.AsyncClient:
    webhook = DependenciasWebhook(ConfigWebhook("s", 10), None, None)  # type: ignore[arg-type]
    panico = DependenciasPanico(
        hashlib.sha256(TOKEN.encode()).hexdigest(), AcionarPanico(Entregas())
    )  # type: ignore[arg-type]
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=criar_app(webhook, panico)), base_url="http://forja"
    )


async def test_com_token_correto_cancela_tudo() -> None:
    async with cliente() as c:
        resposta = await c.post("/panico", headers={"Authorization": f"Bearer {TOKEN}"})
    assert resposta.status_code == 200
    assert resposta.json() == {"cancelados": 4}


@pytest.mark.parametrize("cabecalho", [None, "Bearer errado", "Basic abc", "Bearer"])
async def test_sem_credencial_valida_da_401(cabecalho: str | None) -> None:
    async with cliente() as c:
        resposta = await c.post(
            "/panico", headers={"Authorization": cabecalho} if cabecalho else {}
        )
    assert resposta.status_code == 401
