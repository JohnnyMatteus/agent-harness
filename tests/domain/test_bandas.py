from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from forja.domain.bandas import (
    Amostra,
    Banda,
    Bandas,
    BandasInvalidas,
    EstadoDaBanda,
    avaliar_banda,
    duracao_em_segundos,
)
from forja.infrastructure.yaml_estrito import ler

DOC = """
service: payments-events-go
bands:
  - id: webhook-latency-p95
    query: histogram_quantile(0.95, sum(rate(http_duration_bucket[5m])) by (le))
    max: 0.300
    for: 10m
    on_breach: diagnose_and_write_intent
  - id: dlq-rate
    query: sum(rate(dlq_messages_total[15m]))
    max: 0.1
    for: 15m
"""


def test_le_o_bands_yaml_do_design_doc() -> None:
    b = Bandas.de_dict(ler(DOC))
    assert b.servico == "payments-events-go" and [x.id for x in b.bandas] == [
        "webhook-latency-p95",
        "dlq-rate",
    ]
    assert b.bandas[0].por_segundos == 600 and b.bandas[1].maximo == 0.1


@pytest.mark.parametrize("texto", ["30s", "10m", "1h", "24h"])
def test_duracoes_validas(texto: str) -> None:
    assert duracao_em_segundos(texto) > 0


@pytest.mark.parametrize("texto", ["", "10", "m", "-5m", "10x", "0s", "25h", "1d", "1.5h"])
def test_duracoes_invalidas(texto: str) -> None:
    with pytest.raises(BandasInvalidas):
        duracao_em_segundos(texto)


@pytest.mark.parametrize(
    "dados",
    [
        [],
        {"service": "s", "extra": 1},
        {"bands": []},
        {"service": "s", "bands": "x"},
        {"service": "s", "bands": [{"id": "A B", "query": "q", "max": 1, "for": "1m"}]},
        {"service": "s", "bands": [{"id": "a", "query": "q", "max": "1", "for": "1m"}]},
        {
            "service": "s",
            "bands": [{"id": "a", "query": "q", "max": 1, "for": "1m", "on_breach": "rm -rf"}],
        },
        {"service": "s", "bands": [{"id": "a", "query": "q", "max": 1, "for": "1m", "x": 1}]},
        {"service": "s", "bands": [{"id": "a", "query": "q\nx", "max": 1, "for": "1m"}]},
        {"service": "s", "bands": [{"id": "a", "query": "x" * 1001, "max": 1, "for": "1m"}]},
        {"service": "s", "bands": [{"id": "a", "query": "q", "max": 1, "for": "1m"}] * 2},
    ],
)
def test_bands_invalido_e_recusado(dados: object) -> None:
    with pytest.raises(BandasInvalidas):
        Bandas.de_dict(dados)


B = Banda("lat", "q", 0.3, 600)


def serie(valores: list[float], passo: int = 60, fim: float = 1000.0) -> list[Amostra]:
    n = len(valores)
    return [Amostra(fim - (n - 1 - i) * passo, v) for i, v in enumerate(valores)]


V, D, N = EstadoDaBanda.VIOLADA, EstadoDaBanda.DENTRO, EstadoDaBanda.SEM_DADOS


def estado(valores_ou_serie: list[Any], agora: float = 1000.0) -> EstadoDaBanda:
    s = (
        valores_ou_serie
        if valores_ou_serie and isinstance(valores_ou_serie[0], Amostra)
        else (serie(valores_ou_serie))
    )
    return avaliar_banda(B, s, agora, 60)[0]


def test_violacao_exige_a_janela_inteira_acima_do_maximo() -> None:
    assert estado([0.5] * 11) is V
    assert estado([0.5] * 5 + [0.2] + [0.5] * 5) is D  # um vale quebra a violação
    assert estado([0.3] * 11) is D  # igual ao teto não viola
    assert estado([0.1] * 20 + [0.5] * 11) is V  # só a janela conta


def test_sem_dados_nunca_vira_dentro_nem_violada() -> None:
    """Falha fechada: série vazia, curta, com NaN ou infinito, velha ou com buraco é SEM_DADOS."""
    assert estado([]) is N
    assert estado([0.5] * 4) is N  # não cobre a janela
    assert estado([0.5] * 10 + [float("nan")]) is N
    assert estado([0.01] * 10 + [float("inf")]) is N
    assert estado([0.01] * 11, agora=1000.0 + 600) is N  # dado velho: não é "dentro"
    com_buraco = [a for a in serie([0.01] * 11) if a.instante not in (700.0, 760.0, 820.0)]
    assert estado(com_buraco) is N
    assert avaliar_banda(B, [], 1000.0, 60) == (N, "série vazia")


@given(st.lists(st.floats(0, 1, allow_nan=False), min_size=11, max_size=40))
def test_violada_so_se_toda_a_janela_passa_do_teto(valores: list[float]) -> None:
    s = serie(valores)
    janela = [a.valor for a in s if a.instante >= 1000.0 - 600]
    assert estado(s) is (V if all(v > 0.3 for v in janela) else D)
