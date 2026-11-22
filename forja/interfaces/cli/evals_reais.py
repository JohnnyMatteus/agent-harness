"""Camada de evals com MODELO REAL: manual, desligada e sem implementação (ADR 0047).

Sai com erro, sempre: nunca é verde por ter pulado. Sem configuração completa o erro lista o que
falta (2); com tudo configurado, falta o que só o autor decide (3). Lê apenas o ambiente do
processo (nunca `.env`), não cria segredo e não chama API.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from typing import TextIO

OBRIGATORIAS = {
    "FORJA_EVAL_MODELO_REAL": "opt-in explícito (true) para rodar com modelo real",
    "ANTHROPIC_API_KEY": "chave da API (do operador, só no ambiente do processo)",
    "FORJA_EVAL_MODELO": "modelo avaliado (decisão do autor)",
    "FORJA_EVAL_RUBRICA": "rubrica de qualidade (decisão do autor)",
    "FORJA_EVAL_LIMIAR": "limiar de aprovação (decisão do autor)",
}


def faltando(ambiente: Mapping[str, str]) -> list[str]:
    ausentes = [nome for nome in OBRIGATORIAS if not ambiente.get(nome, "").strip()]
    if ambiente.get("FORJA_EVAL_MODELO_REAL", "").strip().lower() != "true" and (
        "FORJA_EVAL_MODELO_REAL" not in ausentes
    ):
        ausentes.append("FORJA_EVAL_MODELO_REAL")
    return ausentes


def main(ambiente: Mapping[str, str], saida: TextIO = sys.stderr) -> int:
    ausentes = faltando(ambiente)
    if ausentes:
        for nome in ausentes:
            print(f"evals com modelo real: falta {nome} ({OBRIGATORIAS[nome]})", file=saida)
        return 2
    print(
        "evals com modelo real: configuração completa, mas a camada NÃO está implementada: "
        "faltam decisões do autor (tarefas reais, rubrica e limiar calibrados). "
        "Falha de propósito.",
        file=saida,
    )
    return 3


if __name__ == "__main__":
    import os

    sys.exit(main(os.environ))
