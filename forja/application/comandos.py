"""Comandos e resultados que o mundo externo pede ao domínio; nenhum tipo de provedor aqui."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class OrigemExterna:
    """De onde veio o pedido: repositório, número da issue e quem pediu."""

    repositorio: str
    numero: int
    url: str

    @property
    def referencia(self) -> str:
        return f"github:{self.repositorio}#{self.numero}"


@dataclass(frozen=True, slots=True)
class CriarIntent:
    origem: OrigemExterna
    titulo: str
    corpo: str
    autor: str


@dataclass(frozen=True, slots=True)
class Parar:
    origem: OrigemExterna
    autor: str


@dataclass(frozen=True, slots=True)
class Confirmar:
    """`/forja confirm`: quem pediu confirma o resumo do intent.md."""

    origem: OrigemExterna
    autor: str


@dataclass(frozen=True, slots=True)
class Aprovar:
    """`/forja approve`: decisão humana num portão (spec com pontos em aberto, PR de risco)."""

    origem: OrigemExterna
    autor: str


@dataclass(frozen=True, slots=True)
class Rejeitar:
    """`/forja reject <motivo>`: o motivo é texto não confiável."""

    origem: OrigemExterna
    autor: str
    motivo: str = ""


@dataclass(frozen=True, slots=True)
class Ignorado:
    motivo: str


Sinalizacao = Confirmar | Aprovar | Rejeitar
Comando = CriarIntent | Parar | Sinalizacao
Traducao = Comando | Ignorado

ResultadoAtivacao = Literal["iniciada", "ja_existia", "sinalizada", "ignorada"]
