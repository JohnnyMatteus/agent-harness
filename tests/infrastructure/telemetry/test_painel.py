# pyright: basic
"""O painel só pode usar métricas que existem (ADR 0047): cada `forja_*` do JSON tem de estar
no /metrics real, e as métricas de eval (pass@k, taxa) não são exportadas, então não há painel."""

import json
import re
from pathlib import Path

from forja.infrastructure.telemetry.metricas import MetricasForja

PAINEL = Path(__file__).parents[3] / "infra" / "observabilidade" / "painel-forja.json"


def _exportadas() -> set[str]:
    texto = MetricasForja().exportar().decode()
    return {
        m.group(1) for m in re.finditer(r"^# TYPE (forja_\w+?)(?:_total)?\s+counter", texto, re.M)
    }


def test_o_painel_so_referencia_metricas_exportadas() -> None:
    painel = json.loads(PAINEL.read_text(encoding="utf-8"))
    exprs = [t["expr"] for p in painel["panels"] for t in p["targets"]]
    assert exprs and all(e.strip() for e in exprs)
    usadas = {m for e in exprs for m in re.findall(r"forja_\w+?(?:_total)", e)}
    exportadas = {f"{n}_total" for n in _exportadas()} | _exportadas()
    assert usadas and usadas <= exportadas, usadas - exportadas


def test_nao_ha_painel_de_metrica_de_eval_que_nao_existe() -> None:
    texto = PAINEL.read_text(encoding="utf-8").lower()
    for inventada in ("pass@k", "pass_at", "pass^k", "taxa_de_eval", "recall", "qualidade"):
        assert inventada not in texto.replace(
            "não há painel de pass@k, qualidade de agente nem taxa de eval", ""
        )
