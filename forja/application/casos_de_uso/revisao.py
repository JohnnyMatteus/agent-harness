"""Revisão da entrega: revisores independentes em paralelo, classificação de risco pela
política e review.md. Check runs e decisão de deploy ficam com o workflow (ADR 0007)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field

from forja.application.portas.agente import UsoModelo
from forja.application.portas.revisao import LeituraDeRevisao, Revisor
from forja.domain.politica import Politica
from forja.domain.revisao import (
    Achado,
    DiffDaEntrega,
    ResultadoDaRevisao,
    renderizar_review,
    tier_com_achados,
)


@dataclass(frozen=True, slots=True)
class RevisaoFeita:
    resultado: ResultadoDaRevisao
    review_md: str
    por_revisor: dict[str, tuple[Achado, ...]]
    diff: DiffDaEntrega
    uso: UsoModelo = field(default_factory=UsoModelo)


class RevisarEntrega:
    def __init__(self, revisores: Sequence[Revisor], leitura: LeituraDeRevisao) -> None:
        self._revisores = revisores
        self._leitura = leitura

    async def executar(
        self,
        repositorio: str,
        branch: str,
        intent_md: str,
        spec_md: str,
        labels: Sequence[str],
        politica: Politica,
    ) -> RevisaoFeita:
        diff = await self._leitura.diff_da_entrega(repositorio, branch)
        # Em paralelo e independentes: um revisor que falha derruba a revisão (não há "aprovado
        # por omissão"): falhar fechado é o que impede um PR de seguir sem revisão.
        feitas = await asyncio.gather(
            *(r.revisar(repositorio, intent_md, spec_md, diff) for r in self._revisores)
        )
        por_revisor = {r.nome: f.achados for r, f in zip(self._revisores, feitas, strict=True)}
        achados = tuple(a for f in feitas for a in f.achados)
        base = politica.classificar(diff.caminhos, labels, diff.linhas_alteradas)
        resultado = ResultadoDaRevisao(achados, tier_com_achados(base, achados))
        resumos = {r.nome: f.resumo for r, f in zip(self._revisores, feitas, strict=True)}
        uso = UsoModelo()
        for f in feitas:
            uso = UsoModelo(
                uso.tokens_entrada + f.uso.tokens_entrada,
                uso.tokens_saida + f.uso.tokens_saida,
                uso.custo_usd + f.uso.custo_usd,
            )
        return RevisaoFeita(
            resultado, renderizar_review(resultado, resumos), por_revisor, diff, uso
        )
