"""Política de raio de impacto e orçamento (seção 9.1): política como código.

Núcleo do autor (seção 14). Sem `.forja/policy.yaml` vale `Politica.padrao_fechado()`: nada é
baixo risco, então toda entrega passa por um humano. O tier final é o maior entre caminhos
tocados, labels e achados dos revisores.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import IntEnum
from functools import lru_cache
from typing import Any, cast

from forja.domain.erros import ErroDeDominio


class PoliticaInvalida(ErroDeDominio):
    """`policy.yaml` fora do formato (o arquivo é do repositório-alvo, não confiável)."""


class Tier(IntEnum):
    BAIXO = 1
    MEDIO = 2
    ALTO = 3

    @property
    def exige_humano(self) -> bool:
        return self is not Tier.BAIXO


@lru_cache(maxsize=256)
def _regex_do_glob(padrao: str) -> re.Pattern[str]:
    saida: list[str] = []
    i = 0
    while i < len(padrao):
        if padrao.startswith("**/", i):
            saida.append("(?:.*/)?")
            i += 3
        elif padrao.startswith("**", i):
            saida.append(".*")
            i += 2
        elif padrao[i] == "*":
            saida.append("[^/]*")
            i += 1
        elif padrao[i] == "?":
            saida.append("[^/]")
            i += 1
        else:
            saida.append(re.escape(padrao[i]))
            i += 1
    return re.compile("".join(saida))


def casar_glob(padrao: str, caminho: str) -> bool:
    return _regex_do_glob(padrao).fullmatch(caminho) is not None


@dataclass(frozen=True, slots=True)
class Orcamento:
    por_intent_usd: float | None = 5.0
    por_noite_usd: float | None = 10.0
    max_sessoes_por_intent: int | None = 20


@dataclass(frozen=True, slots=True)
class Classificacao:
    tier: Tier
    motivos: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Politica:
    altos_paths: tuple[str, ...] = ()
    altos_labels: tuple[str, ...] = ()
    medios_paths: tuple[str, ...] = ()
    medios_max_linhas: int | None = None
    baixos_paths: tuple[str, ...] = ()
    orcamento: Orcamento = Orcamento()
    declarada: bool = False

    @classmethod
    def padrao_fechado(cls) -> Politica:
        return cls()

    def classificar(
        self, caminhos: Iterable[str], labels: Iterable[str], linhas_alteradas: int
    ) -> Classificacao:
        motivos: list[str] = []
        tier = Tier.BAIXO
        lista = list(caminhos)
        if not lista:
            return Classificacao(Tier.ALTO, ("nenhum caminho alterado",))
        if not self.declarada:
            motivos.append("sem policy.yaml: nada é baixo risco")
            tier = Tier.ALTO
        for caminho in lista:
            atual, motivo = self._de_um_caminho(caminho)
            if atual > Tier.BAIXO:
                motivos.append(f"{caminho}: {motivo}")
            tier = max(tier, atual)
        proibidas = {r.lower() for r in self.altos_labels}
        for label in labels:
            if label.lower() in proibidas:
                motivos.append(f"label {label}")
                tier = Tier.ALTO
        if (
            self.medios_max_linhas is not None
            and tier >= Tier.MEDIO
            and linhas_alteradas > self.medios_max_linhas
        ):
            motivos.append(f"{linhas_alteradas} linhas alteradas (máximo {self.medios_max_linhas})")
            tier = Tier.ALTO
        return Classificacao(tier, tuple(motivos))

    def _de_um_caminho(self, caminho: str) -> tuple[Tier, str]:
        if any(casar_glob(p, caminho) for p in self.altos_paths):
            return Tier.ALTO, "caminho de alto risco"
        if any(casar_glob(p, caminho) for p in self.baixos_paths):
            return Tier.BAIXO, ""
        if any(casar_glob(p, caminho) for p in self.medios_paths):
            return Tier.MEDIO, "caminho de risco médio"
        return Tier.MEDIO, "caminho fora de qualquer tier"

    def estourou_orcamento(self, custo_usd: float, sessoes: int) -> str | None:
        o = self.orcamento
        if o.por_intent_usd is not None and custo_usd >= o.por_intent_usd:
            return (
                f"orçamento por intenção esgotado ({custo_usd:.2f} de {o.por_intent_usd:.2f} USD)"
            )
        if o.max_sessoes_por_intent is not None and sessoes >= o.max_sessoes_por_intent:
            return f"limite de {o.max_sessoes_por_intent} sessões por intenção atingido"
        return None

    @classmethod
    def de_dict(cls, dados: object) -> Politica:
        """Valida o conteúdo já lido do `policy.yaml`. Chave desconhecida é recusada."""
        permitido = {"risk_tiers", "budgets"}
        if not isinstance(dados, Mapping) or set(dados) - permitido:  # pyright: ignore[reportUnknownArgumentType]
            raise PoliticaInvalida("policy.yaml: chaves de topo aceitas são risk_tiers e budgets")
        dados = cast("Mapping[str, Any]", dados)
        tiers = _mapa(dados.get("risk_tiers"), {"high", "medium", "low"}, "risk_tiers")
        alto = _mapa(tiers.get("high"), {"paths", "labels"}, "high")
        medio = _mapa(tiers.get("medium"), {"paths", "max_diff_lines"}, "medium")
        baixo = _mapa(tiers.get("low"), {"paths"}, "low")
        budgets = _mapa(
            dados.get("budgets"),
            {"per_intent_usd", "per_night_usd", "max_sessions_per_intent"},
            "budgets",
        )
        padrao = Orcamento()
        return cls(
            altos_paths=_textos(alto.get("paths"), "high.paths"),
            altos_labels=_textos(alto.get("labels"), "high.labels"),
            medios_paths=_textos(medio.get("paths"), "medium.paths"),
            medios_max_linhas=_numero(medio.get("max_diff_lines"), int, "max_diff_lines"),
            baixos_paths=_textos(baixo.get("paths"), "low.paths"),
            orcamento=Orcamento(
                _numero(
                    budgets.get("per_intent_usd"), float, "per_intent_usd", padrao.por_intent_usd
                ),
                _numero(budgets.get("per_night_usd"), float, "per_night_usd", padrao.por_noite_usd),
                _numero(
                    budgets.get("max_sessions_per_intent"),
                    int,
                    "max_sessions_per_intent",
                    padrao.max_sessoes_por_intent,
                ),
            ),
            declarada=True,
        )


def _mapa(valor: Any, chaves: set[str], nome: str) -> Mapping[str, Any]:
    if valor is None:
        return {}
    if not isinstance(valor, Mapping) or set(valor) - chaves:  # pyright: ignore[reportUnknownArgumentType]
        raise PoliticaInvalida(f"policy.yaml: `{nome}` inválido (aceita {sorted(chaves)})")
    return valor  # pyright: ignore[reportUnknownVariableType]


def _textos(valor: Any, nome: str) -> tuple[str, ...]:
    if valor is None:
        return ()
    if (
        not isinstance(valor, Sequence)
        or isinstance(valor, str)
        or not all(
            isinstance(v, str) and 0 < len(v) <= 200
            for v in valor  # pyright: ignore[reportUnknownVariableType]
        )
    ):
        raise PoliticaInvalida(f"policy.yaml: `{nome}` deve ser lista de textos curtos")
    return tuple(str(v) for v in cast("Sequence[object]", valor))


def _numero[N: (int, float)](
    valor: Any, tipo: type[N], nome: str, padrao: N | None = None
) -> N | None:
    if valor is None:
        return padrao
    if isinstance(valor, bool) or not isinstance(valor, int | float) or valor <= 0:
        raise PoliticaInvalida(f"policy.yaml: `{nome}` deve ser número positivo")
    return tipo(valor)
