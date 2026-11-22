"""Eval do RAG no CI: embeddings falsos e corpus inventado (ver o aviso no próprio resultado)."""

import json

from forja.infrastructure.knowledge.avaliacao import (
    AVISO,
    RAIZ_DO_EVAL,
    VERSAO_DAS_METRICAS,
    avaliar,
    regressoes,
)

BASELINE = json.loads((RAIZ_DO_EVAL / "baseline.json").read_text(encoding="utf-8"))


def test_baseline_nao_alega_qualidade_de_modelo_real() -> None:
    assert BASELINE["embedder"].startswith("falso-")
    assert BASELINE["aviso"] == AVISO
    assert BASELINE["versao_metricas"] == VERSAO_DAS_METRICAS


def test_corpus_e_perguntas_batem_com_a_baseline() -> None:
    atual = avaliar()
    assert atual["corpus_sha"] == BASELINE["corpus_sha"], (
        "corpus ou perguntas mudaram: rode "
        "`uv run python -m forja.infrastructure.knowledge.avaliacao --atualizar` e revise o diff"
    )
    assert atual["pipeline"] == BASELINE["pipeline"], "pipeline mudou: renove a baseline"


def test_nenhuma_metrica_regride_e_o_resultado_e_deterministico() -> None:
    atual = avaliar()
    assert regressoes(BASELINE, atual) == []
    assert avaliar() == atual


def test_detector_de_regressao() -> None:
    base = {"metricas": {"recall@1": 0.6, "mrr": 0.7}}
    assert regressoes(base, {"metricas": {"recall@1": 0.6, "mrr": 0.9}}) == []
    assert regressoes(base, {"metricas": {"recall@1": 0.5, "mrr": 0.7}}) == ["recall@1: 0.6 -> 0.5"]
