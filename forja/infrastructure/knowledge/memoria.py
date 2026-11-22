"""Índice em memória: dublê de teste e adaptador do eval no CI. Não é o índice de produção.

Implementa a mesma porta que o Postgres, com BM25 de verdade (k1=1,5; b=0,75) e cosseno.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence

from forja.domain.knowledge import Escopo, Filtro, Trecho
from forja.infrastructure.knowledge.texto import termos

_K1 = 1.5
_B = 0.75


def _aceita(trecho: Trecho, filtro: Filtro) -> bool:
    return (filtro.tipos is None or trecho.tipo in filtro.tipos) and (
        filtro.linguagem is None or trecho.linguagem == filtro.linguagem
    )


class IndiceEmMemoria:
    def __init__(self) -> None:
        self._dados: dict[Escopo, dict[str, tuple[str, list[tuple[Trecho, list[float]]]]]] = {}

    def versoes_por_arquivo(self, escopo: Escopo) -> dict[str, str]:
        return {c: v for c, (v, _) in self._dados.get(escopo, {}).items()}

    def substituir_arquivo(
        self,
        escopo: Escopo,
        caminho: str,
        versao: str,
        itens: Sequence[tuple[Trecho, Sequence[float]]],
    ) -> None:
        for trecho, _ in itens:
            if trecho.escopo != escopo or trecho.caminho != caminho:
                raise ValueError("trecho fora do escopo ou do caminho informado")
        self._dados.setdefault(escopo, {})[caminho] = (versao, [(t, list(v)) for t, v in itens])

    def remover_arquivo(self, escopo: Escopo, caminho: str) -> None:
        self._dados.get(escopo, {}).pop(caminho, None)

    def _candidatos(self, escopo: Escopo, filtro: Filtro) -> list[tuple[Trecho, list[float]]]:
        return [
            par
            for _, itens in self._dados.get(escopo, {}).values()
            for par in itens
            if _aceita(par[0], filtro)
        ]

    def buscar_lexical(
        self, escopo: Escopo, consulta: str, limite: int, filtro: Filtro
    ) -> list[Trecho]:
        docs = [(t, Counter(termos(t.texto_indexado))) for t, _ in self._candidatos(escopo, filtro)]
        consultados = set(termos(consulta))
        if not docs or not consultados:
            return []
        media = sum(sum(c.values()) for _, c in docs) / len(docs)
        pontos: list[tuple[float, str, Trecho]] = []
        for trecho, contagem in docs:
            tamanho = sum(contagem.values())
            nota = 0.0
            for termo in consultados:
                frequencia = contagem.get(termo, 0)
                if not frequencia:
                    continue
                com_termo = sum(1 for _, c in docs if termo in c)
                idf = math.log(1 + (len(docs) - com_termo + 0.5) / (com_termo + 0.5))
                nota += (
                    idf
                    * frequencia
                    * (_K1 + 1)
                    / (frequencia + _K1 * (1 - _B + _B * tamanho / media))
                )
            if nota > 0:
                pontos.append((nota, trecho.id, trecho))
        pontos.sort(key=lambda p: (-p[0], p[1]))
        return [t for _, _, t in pontos[:limite]]

    def buscar_vetorial(
        self, escopo: Escopo, vetor: Sequence[float], limite: int, filtro: Filtro
    ) -> list[Trecho]:
        pontos = [
            (sum(a * b for a, b in zip(vetor, v, strict=True)), t.id, t)
            for t, v in self._candidatos(escopo, filtro)
        ]
        pontos.sort(key=lambda p: (-p[0], p[1]))
        return [t for _, _, t in pontos[:limite]]

    def obter_simbolo(self, escopo: Escopo, caminho: str, simbolo: str) -> list[Trecho]:
        _, itens = self._dados.get(escopo, {}).get(caminho, ("", []))
        return sorted((t for t, _ in itens if t.simbolo == simbolo), key=lambda t: t.linha_inicio)
