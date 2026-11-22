"""Portas dos agentes do SDLC. O que entra é texto não confiável; o que sai já foi validado
por schema e vira objeto de domínio (nunca texto livre de modelo)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from forja.application.portas.agente import UsoModelo
from forja.domain.artefatos import IntentMd, Plano, Spec


@dataclass(frozen=True, slots=True)
class Pedido:
    """O que a Intent trouxe de fora: tudo aqui é dado, não instrução."""

    repositorio: str
    numero: int
    titulo: str
    corpo: str
    url: str | None = None


@dataclass(frozen=True, slots=True)
class Resultado[T]:
    valor: T
    uso: UsoModelo = field(default_factory=UsoModelo)


class Interprete(Protocol):
    async def interpretar(self, pedido: Pedido) -> Resultado[IntentMd]: ...


class Especificador(Protocol):
    async def especificar(self, repositorio: str, intent_md: str) -> Resultado[Spec]: ...


class Planejador(Protocol):
    async def planejar(
        self, repositorio: str, intent_md: str, spec_md: str
    ) -> Resultado[Plano]: ...


@dataclass(frozen=True, slots=True)
class FonteRecuperada:
    id: str
    caminho: str
    commit: str
    tipo: str
    texto: str


class PesquisaDeConhecimento(Protocol):
    """Porta de consulta ao RAG (M2). Quem chama é código do workflow, nunca o agente."""

    async def pesquisar(
        self, repositorio: str, consulta: str, tipo: str | None, k: int
    ) -> list[FonteRecuperada]: ...


class ListadorDeArquivos(Protocol):
    async def listar(self, repositorio: str) -> tuple[str, ...]:
        """Arquivos versionados do repositório-alvo, só caminhos."""
        ...
