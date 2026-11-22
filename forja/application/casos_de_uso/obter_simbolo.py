from __future__ import annotations

from forja.application.portas.knowledge import IndiceDeTrechos
from forja.domain.knowledge import Escopo, Trecho


class ObterSimbolo:
    """Partes de um símbolo, em ordem de linha, só do escopo pedido (o índice não é confiável)."""

    def __init__(self, indice: IndiceDeTrechos) -> None:
        self._indice = indice

    def executar(self, escopo: Escopo, caminho: str, simbolo: str) -> list[Trecho]:
        partes = self._indice.obter_simbolo(escopo, caminho, simbolo)
        return sorted(
            (t for t in partes if t.escopo == escopo and t.caminho == caminho),
            key=lambda t: t.linha_inicio,
        )
