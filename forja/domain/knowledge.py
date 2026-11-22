"""Vocabulário do contexto Knowledge: escopo de isolamento, trecho e fusão de rankings."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from forja.domain.erros import ErroDeDominio


class TipoDeTrecho(StrEnum):
    CODIGO = "codigo"
    ADR = "adr"
    DOC = "doc"


@dataclass(frozen=True, slots=True)
class Escopo:
    """Fronteira de isolamento: toda leitura e escrita do índice carrega um Escopo."""

    organizacao: str
    repositorio: str

    def __post_init__(self) -> None:
        for nome, valor in (("organizacao", self.organizacao), ("repositorio", self.repositorio)):
            if not valor or valor != valor.strip() or any(c.isspace() for c in valor):
                raise ErroDeDominio(f"escopo invalido: {nome} vazio ou com espaco")


@dataclass(frozen=True, slots=True)
class TrechoBruto:
    """Saída do chunker, antes de receber identidade e contexto."""

    simbolo: str | None
    linha_inicio: int
    linha_fim: int
    conteudo: str


@dataclass(frozen=True, slots=True)
class Trecho:
    id: str
    escopo: Escopo
    caminho: str
    linguagem: str
    tipo: TipoDeTrecho
    simbolo: str | None
    linha_inicio: int
    linha_fim: int
    conteudo: str
    contexto: str
    commit: str

    @property
    def texto_indexado(self) -> str:
        """Texto com o prefixo de contexto: vai para o embedding e para o índice textual."""
        return f"{self.contexto}\n{self.conteudo}" if self.contexto else self.conteudo


@dataclass(frozen=True, slots=True)
class Resultado:
    trecho: Trecho
    score: float


def id_do_trecho(escopo: Escopo, caminho: str, ordem: int, conteudo: str) -> str:
    """Estável entre reindexações de conteúdo idêntico; muda quando o trecho muda."""
    base = "\x00".join(
        [escopo.organizacao, escopo.repositorio, caminho, str(ordem), conteudo]
    ).encode()
    return hashlib.sha256(base).hexdigest()[:32]


def fundir_rrf(rankings: Sequence[Sequence[str]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion: soma 1/(k+posição) por lista; desempate pelo id, determinístico."""
    pontos: dict[str, float] = {}
    for ranking in rankings:
        for posicao, id_ in enumerate(ranking, start=1):
            pontos[id_] = pontos.get(id_, 0.0) + 1.0 / (k + posicao)
    return sorted(pontos.items(), key=lambda par: (-par[1], par[0]))


@dataclass(frozen=True, slots=True)
class Filtro:
    """Filtros de metadado aplicados dentro da consulta, antes do ranqueamento."""

    tipos: frozenset[TipoDeTrecho] | None = None
    linguagem: str | None = None
