# pyright: basic
import httpx
import pytest
import respx

from forja.infrastructure.telemetry.prometheus import (
    MAX_PONTOS,
    PrometheusHttp,
    PrometheusIndisponivel,
    validar_url_do_prometheus,
)

BASE = "http://prom.test"


def resposta(valores):
    return {
        "status": "success",
        "data": {"resultType": "matrix", "result": [{"metric": {}, "values": valores}]},
    }


async def test_devolve_a_serie_e_envia_a_consulta_como_parametro_de_leitura() -> None:
    async with httpx.AsyncClient(base_url=BASE) as http, respx.mock(base_url=BASE) as mock:
        rota = mock.get("/api/v1/query_range").respond(
            200, json=resposta([[100, "0.5"], [160, "0.6"]])
        )
        s = await PrometheusHttp(http, relogio=lambda: 1000.0).serie("sum(rate(x[5m]))", 600, 60)
        assert [(a.instante, a.valor) for a in s] == [(100.0, 0.5), (160.0, 0.6)]
        req = rota.calls.last.request
        assert req.method == "GET" and "query=sum" in str(req.url) and "start=400" in str(req.url)


@pytest.mark.parametrize(
    "corpo",
    [
        {"status": "error", "errorType": "bad_data"},
        {"status": "success", "data": {"resultType": "vector", "result": []}},
        resposta([["a", "b"]]),
        {"status": "success", "data": {"resultType": "matrix", "result": []}},
        {
            "status": "success",
            "data": {"resultType": "matrix", "result": [{"values": []}, {"values": []}]},
        },
        {"nada": 1},
    ],
)
async def test_resposta_estranha_nunca_vira_serie(corpo) -> None:
    async with httpx.AsyncClient(base_url=BASE) as http, respx.mock(base_url=BASE) as mock:
        mock.get("/api/v1/query_range").respond(200, json=corpo)
        with pytest.raises(PrometheusIndisponivel):
            await PrometheusHttp(http).serie("q", 600, 60)


async def test_http_de_erro_e_tetos() -> None:
    async with httpx.AsyncClient(base_url=BASE) as http, respx.mock(base_url=BASE) as mock:
        mock.get("/api/v1/query_range").respond(503)
        with pytest.raises(PrometheusIndisponivel, match="503"):
            await PrometheusHttp(http).serie("q", 600, 60)
        for args in (("x" * 2000, 600, 60), ("q", 10**6, 1), ("q", 600, 0)):
            with pytest.raises(PrometheusIndisponivel, match="tetos"):
                await PrometheusHttp(http).serie(*args)


async def test_warning_resposta_cortada_e_erro_de_rede_nunca_viram_serie() -> None:
    async with httpx.AsyncClient(base_url=BASE) as http, respx.mock(base_url=BASE) as mock:
        rota = mock.get("/api/v1/query_range")
        com_aviso = {**resposta([[100, "0.5"]]), "warnings": ["resultado parcial"]}
        rota.respond(200, json=com_aviso)
        with pytest.raises(PrometheusIndisponivel, match="avisos"):
            await PrometheusHttp(http).serie("q", 600, 60)
        # uma resposta acima do teto não é lida pela metade (o corte esconderia o fim da série)
        grande = resposta([[i, "0.5"] for i in range(MAX_PONTOS + 1)])
        rota.respond(200, json=grande)
        with pytest.raises(PrometheusIndisponivel, match="teto"):
            await PrometheusHttp(http).serie("q", 600, 1)
        rota.side_effect = httpx.ConnectError("recusou")
        with pytest.raises(PrometheusIndisponivel, match="inacessível"):
            await PrometheusHttp(http).serie("q", 600, 60)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://x",
        "http://u:p@prom:9090",
        "http://prom?x=1",
        "http:///",
        "prom",
    ],
)
def test_url_do_prometheus_so_http_sem_credencial_nem_consulta(url: str) -> None:
    with pytest.raises(ValueError, match="FORJA_PROMETHEUS_URL"):
        validar_url_do_prometheus(url)


def test_url_valida_perde_a_barra_final() -> None:
    assert validar_url_do_prometheus("https://prom.interno:9090/ ") == "https://prom.interno:9090"
