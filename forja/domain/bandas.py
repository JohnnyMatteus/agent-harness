"""Bandas de produção (seção 10.2): limites de métrica que, violados por um tempo, abrem um
incidente. As bandas são do OPERADOR (arquivo fora do repositório monitorado, ver
`bandas_do_operador`); a consulta PromQL só é executada por um adaptador somente leitura e com
teto de tamanho. O repositório monitorado, as issues e o modelo nunca escolhem a consulta."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from typing import Any, cast

from forja.domain.erros import ErroDeDominio

_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,59}")
_DURACAO = re.compile(r"(\d{1,4})([smh])")
_UNIDADE = {"s": 1, "m": 60, "h": 3600}
ACOES = frozenset({"diagnose_and_write_intent"})
MAX_CONSULTA = 1_000
MAX_BANDAS = 50
# `for` menor que o passo da série (60 s) não teria amostra para cobri-lo: o arquivo é recusado.
MIN_FOR_S = 60


class BandasInvalidas(ErroDeDominio):
    """Arquivo de bandas do operador fora do formato."""


def duracao_em_segundos(texto: str) -> int:
    achado = _DURACAO.fullmatch(texto.strip())
    if achado is None:
        raise BandasInvalidas(f"duração inválida: {texto[:20]!r} (use 30s, 10m ou 1h)")
    segundos = int(achado.group(1)) * _UNIDADE[achado.group(2)]
    if not 0 < segundos <= 24 * 3600:
        raise BandasInvalidas("duração fora de 1 s a 24 h")
    return segundos


def _for_do_arquivo(texto: str) -> int:
    segundos = duracao_em_segundos(texto)
    if segundos < MIN_FOR_S:
        raise BandasInvalidas(f"`for` mínimo é {MIN_FOR_S}s (o passo da série): recusado")
    return segundos


@dataclass(frozen=True, slots=True)
class Banda:
    id: str
    consulta: str
    maximo: float
    por_segundos: int
    ao_violar: str = "diagnose_and_write_intent"

    def __post_init__(self) -> None:
        if _ID.fullmatch(self.id) is None:
            raise BandasInvalidas(f"id de banda inválido: {self.id[:40]!r}")
        if not self.consulta.strip() or len(self.consulta) > MAX_CONSULTA or "\n" in self.consulta:
            raise BandasInvalidas("consulta vazia, com quebra de linha ou acima do teto")
        if not math.isfinite(self.maximo):
            raise BandasInvalidas("banda: `max` deve ser finito (nem NaN nem infinito)")
        if self.por_segundos < 1:
            raise BandasInvalidas("banda: `for` deve ser positivo")
        if self.ao_violar not in ACOES:
            raise BandasInvalidas(f"ação desconhecida: {self.ao_violar[:40]!r}")


@dataclass(frozen=True, slots=True)
class Bandas:
    servico: str
    bandas: tuple[Banda, ...]

    @classmethod
    def de_dict(cls, dados: object) -> Bandas:
        if not isinstance(dados, Mapping) or set(dados) - {"service", "bands"}:  # pyright: ignore[reportUnknownArgumentType]
            raise BandasInvalidas("bandas: chaves aceitas são service e bands")
        bruto = cast("Mapping[str, Any]", dados)
        servico = bruto.get("service")
        itens = bruto.get("bands", [])
        if not isinstance(servico, str) or not servico.strip() or len(servico) > 100:
            raise BandasInvalidas("bandas: `service` ausente ou inválido")
        if not isinstance(itens, Sequence) or isinstance(itens, str) or len(itens) > MAX_BANDAS:  # pyright: ignore[reportUnknownArgumentType]
            raise BandasInvalidas("bandas: `bands` deve ser lista de até 50 itens")
        bandas: list[Banda] = []
        for item in cast("Sequence[object]", itens):
            if not isinstance(item, Mapping) or set(item) - {  # pyright: ignore[reportUnknownArgumentType]
                "id",
                "query",
                "max",
                "for",
                "on_breach",
            }:
                raise BandasInvalidas(
                    "banda com campo desconhecido (aceita id, query, max, for, on_breach)"
                )
            b = cast("Mapping[str, Any]", item)
            maximo = b.get("max")
            if isinstance(maximo, bool) or not isinstance(maximo, int | float):
                raise BandasInvalidas("banda: `max` deve ser número")
            bandas.append(
                Banda(
                    str(b.get("id", "")),
                    str(b.get("query", "")),
                    float(maximo),
                    _for_do_arquivo(str(b.get("for", ""))),
                    str(b.get("on_breach", "diagnose_and_write_intent")),
                )
            )
        if len({b.id for b in bandas}) != len(bandas):
            raise BandasInvalidas("ids de banda repetidos")
        return cls(servico.strip(), tuple(bandas))


@dataclass(frozen=True, slots=True)
class Amostra:
    instante: float
    valor: float


class EstadoDaBanda(StrEnum):
    VIOLADA = "violada"
    DENTRO = "dentro"
    SEM_DADOS = "sem_dados"  # não sabemos: nunca vale como "dentro" nem como "recuperado"


def janela_avaliada(banda: Banda, serie: Sequence[Amostra], agora: float) -> list[Amostra]:
    """As amostras que decidem a banda: a que cobre o início da janela (a última até `inicio`,
    pois vale até a seguinte) e todas as posteriores."""
    inicio = agora - banda.por_segundos
    anteriores = [a for a in serie if a.instante <= inicio]
    depois = [a for a in serie if a.instante > inicio]
    return ([anteriores[-1]] if anteriores else []) + depois


def avaliar_banda(
    banda: Banda, serie: Sequence[Amostra], agora: float, passo_s: int
) -> tuple[EstadoDaBanda, str]:
    """Falha fechada: só afirma `DENTRO` ou `VIOLADA` com dado completo e fresco; qualquer lacuna
    é `SEM_DADOS` com o motivo (série vazia, NaN ou infinito, janela não coberta, buracos ou dado
    velho). `agora` é o mesmo instante `end` da consulta. Violada é TODA amostra desde o início da
    janela `for` (inclusive a que o cobre) até `agora` ACIMA do máximo."""
    if not serie:
        return EstadoDaBanda.SEM_DADOS, "série vazia"
    if any(not math.isfinite(a.valor) for a in serie):
        return EstadoDaBanda.SEM_DADOS, "valor não finito (NaN ou infinito) na série"
    inicio = agora - banda.por_segundos
    if serie[0].instante > inicio:
        return EstadoDaBanda.SEM_DADOS, "a série não tem amostra cobrindo o início da janela"
    if serie[-1].instante < agora - 2 * passo_s:
        return EstadoDaBanda.SEM_DADOS, "a série está desatualizada"
    janela = janela_avaliada(banda, serie, agora)
    if any(b.instante - a.instante > 2 * passo_s for a, b in pairwise(janela)):
        return EstadoDaBanda.SEM_DADOS, "buracos na janela"
    if all(a.valor > banda.maximo for a in janela):
        return EstadoDaBanda.VIOLADA, ""
    return EstadoDaBanda.DENTRO, ""
