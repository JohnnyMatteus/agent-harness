"""Embeddings falsos e determinísticos: hashing de termos, sem modelo e sem rede.

Servem para exercitar o encanamento (indexação, fusão, isolamento, métricas) no CI.
Não medem qualidade semântica: nenhuma métrica obtida com eles vale para um modelo real.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

from forja.infrastructure.knowledge.texto import termos


class EmbedderFalso:
    def __init__(self, dimensao: int = 64) -> None:
        self.dimensao = dimensao
        self.versao = f"falso-hash-{dimensao}"

    def embutir(self, textos: Sequence[str]) -> list[list[float]]:
        return [self._um(t) for t in textos]

    def _um(self, texto: str) -> list[float]:
        vetor = [0.0] * self.dimensao
        for termo in termos(texto):
            resumo = hashlib.sha256(termo.encode()).digest()
            posicao = int.from_bytes(resumo[:4], "big") % self.dimensao
            vetor[posicao] += 1.0 if resumo[4] & 1 else -1.0
        norma = math.sqrt(sum(x * x for x in vetor))
        return [x / norma for x in vetor] if norma else vetor
