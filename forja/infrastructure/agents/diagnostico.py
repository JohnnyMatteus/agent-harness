"""Diagnóstico multiagente (seção 10.2, ADR 0017): pesquisadores em paralelo e um líder.

Sem ferramenta: métricas, deploys e trechos do RAG chegam por código, como dado delimitado, e a
evidência numérica é calculada por código. O líder só pode citar fontes que o RAG devolveu.
"""

from __future__ import annotations

import asyncio

from forja.application.portas.sdlc import FonteRecuperada, PesquisaDeConhecimento, Resultado
from forja.domain.artefatos import Fonte
from forja.domain.bandas import Banda
from forja.domain.incidente import Evidencia, Incidente
from forja.domain.seguranca import dado_nao_confiavel
from forja.infrastructure.agents.esquemas import IncidenteSaida
from forja.infrastructure.agents.estruturado import AgenteEstruturado

TRECHO_MAX = 1_200
# Corpus consultado: incidentes anteriores (incident.md indexados como documento) e ADRs.
FOCOS: tuple[tuple[str, str | None], ...] = (("incidentes parecidos", "doc"), ("decisões", "adr"))


class DiagnosticoMultiagente:
    def __init__(
        self, pesquisa: PesquisaDeConhecimento, lider: AgenteEstruturado[IncidenteSaida]
    ) -> None:
        self._pesquisa = pesquisa
        self._lider = lider

    async def diagnosticar(
        self, repositorio: str, banda: Banda, evidencia: Evidencia, deploys: list[str]
    ) -> Resultado[Incidente]:
        consulta = f"{banda.id} {evidencia.resumo()}"[:480]
        listas = await asyncio.gather(
            *(self._pesquisa.pesquisar(repositorio, consulta, tipo, 5) for _, tipo in FOCOS)
        )
        fontes: dict[str, FonteRecuperada] = {f.id: f for lista in listas for f in lista}
        texto = (
            f"<evidencia>{dado_nao_confiavel(evidencia.resumo())}</evidencia>\n"
            f"<deploys>{dado_nao_confiavel(chr(10).join(deploys[:20]))}</deploys>\n"
            + "\n".join(
                f'<fonte id="{f.id}" caminho="{dado_nao_confiavel(f.caminho)}">'
                f"{dado_nao_confiavel(f.texto[:TRECHO_MAX])}</fonte>"
                for f in fontes.values()
            )
        )

        def converter(s: IncidenteSaida) -> Incidente:
            desconhecidas = [f for f in s.fontes if f not in fontes]
            if desconhecidas:
                raise ValueError(f"fontes citadas que não foram recuperadas: {desconhecidas[:3]}")
            citadas = tuple(
                Fonte(i, fontes[i].caminho, fontes[i].commit) for i in dict.fromkeys(s.fontes)
            )
            return Incidente(evidencia, s.hipotese, s.proposta, tuple(s.achados), citadas)

        incidente, uso = await self._lider.pedir(f"diagnostico-{banda.id}", texto, converter)
        return Resultado(incidente, uso)
