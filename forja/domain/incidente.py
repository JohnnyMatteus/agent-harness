"""Incidente (seção 10.2): o que o diagnóstico escreve quando uma banda é violada.

O texto vem de modelo e de métricas de sistemas monitorados: tudo é dado. O incident.md e o
corpo da issue são renderizados por código, em uma linha por item, com a evidência numérica
calculada por código (não pelo modelo).
"""

from __future__ import annotations

from dataclasses import dataclass

from forja.domain.artefatos import Fonte, linha_unica
from forja.domain.bandas import Amostra, Banda

ROTULO_DO_INCIDENTE = "forja:incident"


@dataclass(frozen=True, slots=True)
class Evidencia:
    """Fatos medidos, calculados por código a partir da série."""

    banda_id: str
    maximo: float
    por_segundos: int
    atual: float
    pico: float
    amostras: int

    @classmethod
    def da_serie(cls, banda: Banda, serie: list[Amostra]) -> Evidencia:
        valores = [a.valor for a in serie] or [0.0]
        return cls(
            banda.id, banda.maximo, banda.por_segundos, valores[-1], max(valores), len(serie)
        )

    def resumo(self) -> str:
        return (
            f"banda {self.banda_id}: máximo {self.maximo}, atual {self.atual:.4g}, pico "
            f"{self.pico:.4g}, acima do máximo por pelo menos {self.por_segundos}s "
            f"({self.amostras} amostras)"
        )


@dataclass(frozen=True, slots=True)
class Incidente:
    evidencia: Evidencia
    hipotese: str
    proposta: str
    achados: tuple[str, ...]
    fontes: tuple[Fonte, ...] = ()

    def incident_md(self) -> str:
        linhas = ["# incident", "", "## Banda violada", "", self.evidencia.resumo(), ""]
        achados = [f"- {linha_unica(a)}" for a in self.achados] or ["- (nenhuma)"]
        linhas += ["## Evidências", "", *achados]
        linhas += ["", "## Hipótese", "", linha_unica(self.hipotese, 800), ""]
        linhas += ["## Proposta", "", linha_unica(self.proposta, 800), "", "## Fontes", ""]
        linhas += [f"- {f.caminho}@{f.commit[:12]}" for f in self.fontes] or ["- (sem fontes)"]
        return "\n".join(linhas) + "\n"

    def corpo_da_issue(self) -> str:
        """Texto da issue que reabre o ciclo no Plan. Um humano aplica `forja:intent` para o
        Forja agir: a issue criada por bot nunca dispara o fluxo sozinha."""
        return (
            f"Banda `{self.evidencia.banda_id}` violada. {self.evidencia.resumo()}.\n\n"
            f"Hipótese: {linha_unica(self.hipotese, 800)}\n\n"
            f"Proposta: {linha_unica(self.proposta, 800)}\n\n"
            "Para a Forja tratar, aplique o label `forja:intent` (portão humano)."
        )
