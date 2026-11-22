# pyright: basic
from typing import Any

import fakeredis
import httpx
import pytest

from forja.infrastructure.telemetry.metricas import MetricasForja
from forja.interfaces.cli.ajustes import Ajustes
from forja.interfaces.cli.composicao import montar_gateway


def test_ajustes_do_ambiente_com_padroes_seguros(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORJA_REPOS_HABILITADOS", "a/b, c/d")
    ajustes = Ajustes.do_ambiente()
    assert ajustes.repos_habilitados == ["a/b", "c/d"]
    assert ajustes.publicar is False
    monkeypatch.delenv("FORJA_REPOS_HABILITADOS")
    assert Ajustes.do_ambiente().repos_habilitados == []


async def test_gateway_composto_expoe_webhook_panico_e_metricas(
    monkeypatch: pytest.MonkeyPatch, chave_pem: str
) -> None:
    monkeypatch.setenv("FORJA_GITHUB_WEBHOOK_SECRET", "s")
    monkeypatch.setenv("FORJA_GITHUB_APP_ID", "1")
    monkeypatch.setenv("FORJA_GITHUB_APP_PRIVATE_KEY", chave_pem)
    client: Any = object()
    app = montar_gateway(Ajustes.do_ambiente(), client, fakeredis.FakeAsyncRedis(), MetricasForja())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://forja"
    ) as http:
        assert (await http.post("/webhooks/github", content=b"{}")).status_code == 401
        assert (await http.post("/panico")).status_code == 401
        assert "forja_entregas_iniciadas_total" in (await http.get("/metrics")).text
