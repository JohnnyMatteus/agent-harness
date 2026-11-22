"""Consulta somente leitura ao Prometheus (`query_range`). A consulta PromQL vem do
`bands.yaml` do repositório-alvo; ela só é enviada como parâmetro de leitura, com teto de
pontos, e a resposta é validada: erro do Prometheus nunca vira "tudo bem"."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, cast
from urllib.parse import urlsplit

import httpx

from forja.domain.bandas import MAX_CONSULTA, Amostra

MAX_PONTOS = 2_000


class PrometheusIndisponivel(Exception):
    """Consulta falhou ou resposta fora do formato: o monitor não conclui nada com isso."""


def validar_url_do_prometheus(url: str) -> str:
    """A URL vem só da configuração do operador (FORJA_PROMETHEUS_URL), nunca do repositório,
    da issue ou do modelo. Mesmo assim: só http(s), sem credenciais, consulta ou fragmento."""
    partes = urlsplit(url.strip())
    if (
        partes.scheme not in ("http", "https")
        or not partes.hostname
        or partes.username
        or partes.password
        or partes.query
        or partes.fragment
    ):
        raise ValueError(
            "FORJA_PROMETHEUS_URL deve ser http(s)://host[:porta][/prefixo], sem credenciais"
        )
    return url.strip().rstrip("/")


class PrometheusHttp:
    def __init__(self, http: httpx.AsyncClient, relogio: Callable[[], float] = time.time) -> None:
        self._http = http
        self._relogio = relogio

    async def serie(self, consulta: str, janela_s: int, passo_s: int) -> list[Amostra]:
        if len(consulta) > MAX_CONSULTA or passo_s < 1 or janela_s // passo_s > MAX_PONTOS:
            raise PrometheusIndisponivel("consulta ou janela acima dos tetos")
        fim = self._relogio()
        try:
            resposta = await self._http.get(
                "/api/v1/query_range",
                params={"query": consulta, "start": fim - janela_s, "end": fim, "step": passo_s},
            )
        except httpx.HTTPError as erro:
            raise PrometheusIndisponivel(
                f"Prometheus inacessível ({type(erro).__name__})"
            ) from erro
        if resposta.status_code != 200:
            raise PrometheusIndisponivel(f"Prometheus respondeu {resposta.status_code}")
        try:
            corpo = resposta.json()
            if corpo["status"] != "success" or corpo["data"]["resultType"] != "matrix":
                raise PrometheusIndisponivel("resposta não é uma matriz de sucesso")
            if corpo.get("warnings") or corpo.get("infos"):
                # Aviso do Prometheus (ex.: resultado parcial): o dado não é confiável por inteiro.
                raise PrometheusIndisponivel("Prometheus devolveu avisos junto da resposta")
            bruto: Any = corpo["data"]["result"]
            if not isinstance(bruto, list) or len(cast("list[Any]", bruto)) != 1:
                # Várias séries (ou nenhuma) tornam a banda ambígua: o autor agrega na consulta.
                raise PrometheusIndisponivel("a consulta não devolveu exatamente uma série")
            valores: Any = cast("list[Any]", bruto)[0]["values"]
            if not isinstance(valores, list) or len(cast("list[Any]", valores)) > MAX_PONTOS:
                raise PrometheusIndisponivel(
                    "série acima do teto de pontos: não é lida pela metade"
                )
            return [Amostra(float(t), float(v)) for t, v in cast("list[list[Any]]", valores)]
        except (KeyError, ValueError, TypeError, AttributeError) as erro:
            raise PrometheusIndisponivel("resposta do Prometheus fora do formato") from erro
