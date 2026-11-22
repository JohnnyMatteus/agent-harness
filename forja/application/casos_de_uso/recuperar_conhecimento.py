from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from forja.application.portas.knowledge import Embedder, IndiceDeTrechos, Reranker
from forja.domain.knowledge import (
    ConsultaInvalida,
    Escopo,
    Filtro,
    Resultado,
    Trecho,
    fundir_rrf,
)

LIMITE_MAXIMO = 50
CONSULTA_MAXIMA = 500
DESLOCAMENTO_MAXIMO = 200


class SemReranking:
    """Mantém a ordem da fusão. O reranker real (cross-encoder local ou API) está em aberto."""

    def reordenar(self, consulta: str, candidatos: Sequence[Trecho]) -> list[Trecho]:
        return list(candidatos)


@dataclass(frozen=True, slots=True)
class Pagina:
    itens: tuple[Resultado, ...]
    ha_mais: bool


class RecuperarConhecimento:
    """Busca híbrida (lexical + vetorial) com fusão RRF, sempre dentro de um Escopo.

    O escopo é argumento obrigatório e vai para as duas consultas ao índice: não há caminho
    de busca sem ele.
    """

    def __init__(
        self,
        indice: IndiceDeTrechos,
        embedder: Embedder,
        reranker: Reranker | None = None,
        candidatos_por_lista: int = 50,
    ) -> None:
        self._indice = indice
        self._embedder = embedder
        self._reranker: Reranker = reranker or SemReranking()
        self._pool = candidatos_por_lista

    def buscar(
        self,
        escopo: Escopo,
        consulta: str,
        *,
        limite: int = 8,
        deslocamento: int = 0,
        filtro: Filtro | None = None,
    ) -> Pagina:
        if len(consulta) > CONSULTA_MAXIMA:
            raise ConsultaInvalida(f"consulta acima de {CONSULTA_MAXIMA} caracteres")
        if not 0 <= deslocamento <= DESLOCAMENTO_MAXIMO:
            raise ConsultaInvalida(f"deslocamento fora de 0..{DESLOCAMENTO_MAXIMO}")
        limite = max(1, min(limite, LIMITE_MAXIMO))
        filtro = filtro or Filtro()
        if not consulta.strip():
            return Pagina((), False)
        pool = max(self._pool, deslocamento + limite + 1)
        # O índice não é confiável para o isolamento: filtra antes da fusão e do reranker
        # (que pode ser uma API externa) e de novo depois dele.
        lexicais = [
            t
            for t in self._indice.buscar_lexical(escopo, consulta, pool, filtro)
            if t.escopo == escopo
        ]
        (vetor,) = self._embedder.embutir([consulta])
        vetoriais = [
            t
            for t in self._indice.buscar_vetorial(escopo, vetor, pool, filtro)
            if t.escopo == escopo
        ]

        por_id = {t.id: t for t in [*lexicais, *vetoriais]}
        fundidos = fundir_rrf([[t.id for t in lexicais], [t.id for t in vetoriais]])
        pontos = dict(fundidos)
        ordenados = self._reranker.reordenar(consulta, [por_id[i] for i, _ in fundidos])
        ordenados = [t for t in ordenados if t.escopo == escopo and t.id in por_id]
        janela = ordenados[deslocamento : deslocamento + limite]
        return Pagina(
            tuple(Resultado(t, pontos[t.id]) for t in janela),
            ha_mais=len(ordenados) > deslocamento + limite,
        )
