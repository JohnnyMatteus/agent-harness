"""Estratégia de contexto por modelo (ADR 0012): compactação contínua ou reset com handoff,
mais o context editing da API (limpeza de resultados de ferramenta antigos).

O Agent SDK gerencia o contexto sozinho (compacta); o context editing só existe na Messages API
(beta `context-management-2025-06-27`), então é usado onde a Forja conduz o loop: o Avaliador.
O reset com handoff é o próprio desenho do harness: cada sessão do Executor começa limpa e lê
`progress.md`, o contrato e o log do git.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

BETA_CONTEXT_MANAGEMENT = "context-management-2025-06-27"


class Estrategia(StrEnum):
    COMPACTACAO = "compactacao"
    RESET = "reset"


@dataclass(frozen=True, slots=True)
class EstrategiaDeContexto:
    estrategia: Estrategia = Estrategia.RESET
    # Quando o input passa de `gatilho_tokens`, resultados de ferramenta antigos são limpos,
    # mantendo os `manter_usos` mais recentes; limpar menos que `limpar_pelo_menos` não compensa
    # (invalida o cache de prompt).
    gatilho_tokens: int = 60_000
    manter_usos: int = 3
    limpar_pelo_menos: int = 8_000

    def __post_init__(self) -> None:
        if min(self.gatilho_tokens, self.manter_usos, self.limpar_pelo_menos) < 1:
            raise ValueError("limites de contexto devem ser positivos")


PADRAO = EstrategiaDeContexto()
# Por modelo: o autor ajusta conforme o modelo mostrar tendência de encerrar cedo (seção 3A).
POR_MODELO: dict[str, EstrategiaDeContexto] = {}


def estrategia_do_modelo(modelo: str) -> EstrategiaDeContexto:
    return POR_MODELO.get(modelo, PADRAO)


def context_management(
    e: EstrategiaDeContexto, preservar: tuple[str, ...] = ("memory",)
) -> dict[str, Any]:
    """Corpo de `context_management` da Messages API. A ferramenta de memória nunca é limpa:
    o que o agente salvou lá é o que sobrevive à limpeza."""
    return {
        "edits": [
            {
                "type": "clear_tool_uses_20250919",
                "trigger": {"type": "input_tokens", "value": e.gatilho_tokens},
                "keep": {"type": "tool_uses", "value": e.manter_usos},
                "clear_at_least": {"type": "input_tokens", "value": e.limpar_pelo_menos},
                "exclude_tools": list(preservar),
            }
        ]
    }
