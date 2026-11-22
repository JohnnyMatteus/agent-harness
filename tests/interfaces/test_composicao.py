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


def test_harness_falha_fechado_sem_as_condicoes_de_seguranca() -> None:
    from forja.infrastructure.knowledge.configuracao import ConfiguracaoInvalida
    from forja.interfaces.cli.composicao import montar_harness

    base = {"FORJA_HARNESS": "true"}
    casos = [
        ({}, "FORJA_PUBLICAR"),
        ({"FORJA_PUBLICAR": "true"}, "ACEITA_CHAVE_NO_SANDBOX"),
        (
            {"FORJA_PUBLICAR": "true", "FORJA_HARNESS_ACEITA_CHAVE_NO_SANDBOX": "true"},
            "DATABASE_URL",
        ),
        (
            {
                "FORJA_PUBLICAR": "true",
                "FORJA_HARNESS_ACEITA_CHAVE_NO_SANDBOX": "true",
                "DATABASE_URL": "postgresql://x/y",
            },
            "FORJA_MODELO_AVALIADOR",
        ),
        (
            {
                "FORJA_PUBLICAR": "true",
                "FORJA_HARNESS_ACEITA_CHAVE_NO_SANDBOX": "true",
                "DATABASE_URL": "postgresql://x/y",
                "FORJA_MODELO_AVALIADOR": "modelo",
            },
            "FORJA_PRECO_AVALIADOR",
        ),
    ]
    for extra, esperado in casos:
        ajustes = Ajustes.model_validate({**base, **extra})
        with pytest.raises(ConfiguracaoInvalida, match=esperado):
            montar_harness(ajustes, None, None, MetricasForja())  # type: ignore[arg-type]


def _ajustes(monkeypatch: pytest.MonkeyPatch, **env: str) -> Ajustes:
    for k in ("FORJA_MONITOR_REPOS", "FORJA_PROMETHEUS_URL", "FORJA_BANDAS_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FORJA_REPOS_HABILITADOS", "acme/loja")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Ajustes.do_ambiente()


def test_monitor_desligado_sem_configuracao_e_falha_fechado_quando_incompleto(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from forja.infrastructure.knowledge.configuracao import ConfiguracaoInvalida
    from forja.interfaces.cli.composicao import montar_operacao

    github: Any = object()
    pub: Any = object()
    assert montar_operacao(_ajustes(monkeypatch), github, pub) is None  # desligado por padrão
    casos = [
        ({"FORJA_MONITOR_REPOS": "acme/loja"}, "FORJA_PROMETHEUS_URL"),
        (
            {"FORJA_MONITOR_REPOS": "acme/outro", "FORJA_PROMETHEUS_URL": "http://prom:9090",
             "FORJA_BANDAS_DIR": str(tmp_path)},
            "FORJA_REPOS_HABILITADOS",
        ),
        (
            {"FORJA_MONITOR_REPOS": "acme/loja", "FORJA_PROMETHEUS_URL": "http://u:p@prom:9090",
             "FORJA_BANDAS_DIR": str(tmp_path)},
            "credenciais",
        ),
    ]  # fmt: skip
    for env, trecho in casos:
        with pytest.raises(ConfiguracaoInvalida, match=trecho):
            montar_operacao(_ajustes(monkeypatch, **env), github, pub)
    ligado = _ajustes(
        monkeypatch,
        FORJA_MONITOR_REPOS="acme/loja",
        FORJA_PROMETHEUS_URL="http://prom:9090/",
        FORJA_BANDAS_DIR=str(tmp_path),
    )
    assert montar_operacao(ligado, github, pub) is not None
