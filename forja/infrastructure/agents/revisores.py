"""Revisores paralelos (seção 5.4): segurança, testes, aderência a ADRs e desempenho.

Cada um é um agente sem ferramenta: o diff chega por código, como dado delimitado. Os achados
passam por schema e são validados contra o diff; segurança e testes também têm verificação
determinística (scanner de segredos, mudança sem teste) que não depende do modelo.
"""

from __future__ import annotations

from forja.application.portas.revisao import RevisaoDeUmRevisor
from forja.domain.politica import Tier
from forja.domain.revisao import (
    Achado,
    DiffDaEntrega,
    Severidade,
    achado_validado,
    checar_testes,
    varrer_segredos,
)
from forja.domain.seguranca import dado_nao_confiavel
from forja.infrastructure.agents.esquemas import RevisaoDeModeloSaida
from forja.infrastructure.agents.estruturado import AgenteEstruturado

FOCOS = {
    "seguranca": "segurança: OWASP, injeção, autenticação, segredos, entrada não validada.",
    "testes": "testes: cobertura do comportamento novo, testes que não testam o que prometem.",
    "adrs": "aderência aos ADRs e à arquitetura citados na spec; regra de dependência.",
    "desempenho": "desempenho: consultas, laços, alocações e chamadas externas desnecessárias.",
}
TETO_DO_PROMPT = 60_000
_RISCO = {"baixo": Tier.BAIXO, "medio": Tier.MEDIO, "alto": Tier.ALTO}


def foco_do_revisor(nome: str) -> str:
    return f"\nFoco desta revisão: {FOCOS[nome]}"


def texto_do_diff(diff: DiffDaEntrega) -> str:
    partes: list[str] = []
    total = 0
    for a in diff.arquivos:
        bloco = (
            f'<arquivo caminho="{dado_nao_confiavel(a.caminho)}" status="{a.status}" '
            f'mais="{a.adicoes}" menos="{a.remocoes}">{dado_nao_confiavel(a.patch)}</arquivo>'
        )
        total += len(bloco)
        if total > TETO_DO_PROMPT:
            partes.append("<aviso>diff truncado: há mais arquivos</aviso>")
            break
        partes.append(bloco)
    return "\n".join(partes)


class RevisorDeModelo:
    def __init__(
        self, nome: str, agente: AgenteEstruturado[RevisaoDeModeloSaida], skill: str = ""
    ) -> None:
        self._skill = skill  # procedimento do papel, carregado por código (divulgação progressiva)
        if nome not in FOCOS:
            raise ValueError(f"revisor desconhecido: {nome}")
        self.nome = nome
        self._agente = agente

    async def revisar(
        self, repositorio: str, intent_md: str, spec_md: str, diff: DiffDaEntrega
    ) -> RevisaoDeUmRevisor:
        texto = (
            f"<intent>{dado_nao_confiavel(intent_md)}</intent>\n"
            f"<spec>{dado_nao_confiavel(spec_md)}</spec>\n<diff>{texto_do_diff(diff)}</diff>"
        )
        if self._skill:
            texto += f"\n<skill>{dado_nao_confiavel(self._skill)}</skill>"

        def converter(s: RevisaoDeModeloSaida) -> tuple[str, tuple[Achado, ...]]:
            achados = tuple(
                achado_validado(
                    diff,
                    self.nome,
                    Severidade(a.severidade),
                    a.mensagem,
                    a.arquivo,
                    a.linha,
                    _RISCO[a.risco],
                )
                for a in s.achados
            )
            return s.resumo, achados

        (resumo, do_modelo), uso = await self._agente.pedir(
            f"revisao-{self.nome}", texto, converter
        )
        deterministicos = {"seguranca": varrer_segredos, "testes": checar_testes}.get(self.nome)
        extras = deterministicos(diff) if deterministicos else ()
        return RevisaoDeUmRevisor((*extras, *do_modelo), resumo, uso)
