from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from forja.domain.knowledge import Escopo, Filtro, TipoDeTrecho, Trecho, TrechoBruto


@dataclass(frozen=True, slots=True)
class ArquivoFonte:
    caminho: str
    conteudo: str
    sha: str


@dataclass(frozen=True, slots=True)
class Varredura:
    """Arquivos aceitos e, por motivo, quantos foram recusados (nunca o conteúdo recusado)."""

    commit: str
    arquivos: tuple[ArquivoFonte, ...]
    recusados: dict[str, int] = field(default_factory=lambda: {})
    # Caminhos ou diretórios (prefixo) que não puderam ser lidos agora: o que existe no índice
    # sob eles não pode ser removido, porque "não li" não é "foi apagado".
    nao_lidos: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Particao:
    linguagem: str
    tipo: TipoDeTrecho
    trechos: tuple[TrechoBruto, ...]


class FonteDeArquivos(Protocol):
    def varrer(self) -> Varredura: ...


class Chunker(Protocol):
    versao: str

    def dividir(self, caminho: str, texto: str) -> Particao: ...


class Embedder(Protocol):
    versao: str
    dimensao: int

    def embutir(self, textos: Sequence[str]) -> list[list[float]]: ...


class GeradorDeContexto(Protocol):
    """Prefixo de contexto por trecho (ADR 0013)."""

    versao: str

    def contexto(self, caminho: str, simbolo: str | None, particao: Particao) -> str: ...


class Reranker(Protocol):
    def reordenar(self, consulta: str, candidatos: Sequence[Trecho]) -> list[Trecho]: ...


class IndiceDeTrechos(Protocol):
    """Toda operação exige o Escopo e o aplica na própria consulta."""

    def versoes_por_arquivo(self, escopo: Escopo) -> dict[str, str]: ...

    def substituir_arquivo(
        self,
        escopo: Escopo,
        caminho: str,
        versao: str,
        itens: Sequence[tuple[Trecho, Sequence[float]]],
    ) -> None: ...

    def remover_arquivo(self, escopo: Escopo, caminho: str) -> None: ...

    def buscar_lexical(
        self, escopo: Escopo, consulta: str, limite: int, filtro: Filtro
    ) -> list[Trecho]: ...

    def buscar_vetorial(
        self, escopo: Escopo, vetor: Sequence[float], limite: int, filtro: Filtro
    ) -> list[Trecho]: ...

    def obter_simbolo(self, escopo: Escopo, caminho: str, simbolo: str) -> list[Trecho]: ...
