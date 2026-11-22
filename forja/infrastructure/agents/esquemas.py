"""Schemas das saídas de modelo (pydantic). Toda saída de LLM passa por aqui antes de virar
objeto de domínio; campo extra, tamanho acima do teto ou tipo errado é recusado."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from forja.domain.artefatos import Cenario, Fonte, IntentMd, PassoDoPlano, Plano, Spec
from forja.domain.harness import NOTA_MAXIMA, Criterio


class _Saida(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


Texto = Field(min_length=1, max_length=500)


class IntentSaida(_Saida):
    problema: str = Field(min_length=1, max_length=2000)
    criterios_de_sucesso: list[str] = Field(default_factory=list, max_length=20)

    def para_dominio(self, origem: str, url: str | None) -> IntentMd:
        criterios = tuple(c for c in self.criterios_de_sucesso if c.strip())
        return IntentMd(self.problema, criterios, origem, url)


class CenarioSaida(_Saida):
    titulo: str = Field(min_length=1, max_length=200)
    passos: list[str] = Field(min_length=1, max_length=12)


class AchadoSaida(_Saida):
    resumo: str = Field(min_length=1, max_length=800)
    fontes: list[str] = Field(default_factory=list, max_length=10)


class AchadosSaida(_Saida):
    achados: list[AchadoSaida] = Field(default_factory=list[AchadoSaida], max_length=10)


class SpecSaida(_Saida):
    requisitos: list[str] = Field(min_length=1, max_length=30)
    restricoes: list[str] = Field(default_factory=list, max_length=20)
    cenarios: list[CenarioSaida] = Field(min_length=1, max_length=20)
    adrs_afetados: list[str] = Field(default_factory=list, max_length=20)
    pontos_em_aberto: list[str] = Field(default_factory=list, max_length=20)
    fontes: list[str] = Field(default_factory=list, max_length=30)

    def para_dominio(self, disponiveis: dict[str, Fonte]) -> Spec:
        """Citação só vale se a fonte foi de fato recuperada: id inventado é recusado."""
        desconhecidas = [f for f in self.fontes if f not in disponiveis]
        if desconhecidas:
            raise ValueError(f"fontes citadas que não foram recuperadas: {desconhecidas[:3]}")
        return Spec(
            requisitos=tuple(self.requisitos),
            restricoes=tuple(self.restricoes),
            cenarios=tuple(Cenario(c.titulo, tuple(c.passos)) for c in self.cenarios),
            adrs_afetados=tuple(self.adrs_afetados),
            pontos_em_aberto=tuple(p for p in self.pontos_em_aberto if p.strip()),
            fontes=tuple(disponiveis[f] for f in dict.fromkeys(self.fontes)),
        )


class PassoSaida(_Saida):
    arquivo: str = Field(min_length=1, max_length=300)
    mudanca: str = Field(min_length=1, max_length=500)
    testes: list[str] = Field(default_factory=list, max_length=10)


class PlanoSaida(_Saida):
    passos: list[PassoSaida] = Field(min_length=1, max_length=40)

    def para_dominio(self) -> Plano:
        return Plano(
            tuple(PassoDoPlano(p.arquivo, p.mudanca, tuple(p.testes)) for p in self.passos)
        )


class AvaliacaoSaida(_Saida):
    notas: dict[str, int]
    feedback: dict[str, str] = Field(default_factory=dict[str, str])
    defeitos: list[str] = Field(default_factory=list[str], max_length=30)

    def para_dominio(self) -> tuple[dict[Criterio, int], dict[Criterio, str]]:
        validos = {c.value for c in Criterio}
        if set(self.notas) != validos:
            raise ValueError(f"notas devem cobrir exatamente os critérios {sorted(validos)}")
        if any(not 0 <= n <= NOTA_MAXIMA for n in self.notas.values()):
            raise ValueError("nota fora de 0..10")
        feedback = {Criterio(k): v[:800] for k, v in self.feedback.items() if k in validos}
        return {Criterio(k): v for k, v in self.notas.items()}, feedback


class RevisaoSaida(_Saida):
    acordo: bool
    ajustes: list[str] = Field(default_factory=list[str], max_length=20)


class SessaoSaida(_Saida):
    mensagem_de_commit: str = Field(min_length=1, max_length=200)
    resumo: str = Field(min_length=1, max_length=2000)


class FeatureSaida(_Saida):
    id: str = Field(min_length=1, max_length=40)
    categoria: str = Field(min_length=1, max_length=60)
    descricao: str = Field(min_length=1, max_length=500)
    passos_de_teste: list[str] = Field(min_length=1, max_length=10)
    comando_de_teste: list[str] = Field(min_length=1, max_length=20)


class InicializacaoSaida(_Saida):
    features: list[FeatureSaida] = Field(min_length=1, max_length=50)
    comandos_de_setup: list[list[str]] = Field(default_factory=list[list[str]], max_length=10)
    comando_de_fumaca: list[str] = Field(min_length=1, max_length=20)


class ContratoSaida(_Saida):
    features: list[str] = Field(min_length=1, max_length=10)
    entregaveis: list[str] = Field(min_length=1, max_length=10)
    verificacao: list[str] = Field(min_length=1, max_length=10)


class AchadoDoRevisorSaida(_Saida):
    severidade: Literal["bloqueante", "aviso"]
    mensagem: str = Field(min_length=1, max_length=500)
    arquivo: str | None = Field(default=None, max_length=300)
    linha: int | None = Field(default=None, ge=1, le=1_000_000)
    risco: Literal["baixo", "medio", "alto"] = "baixo"


class RevisaoDeModeloSaida(_Saida):
    resumo: str = Field(min_length=1, max_length=600)
    achados: list[AchadoDoRevisorSaida] = Field(
        default_factory=list[AchadoDoRevisorSaida], max_length=30
    )
