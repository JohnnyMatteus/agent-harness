"""Porta de escrita externa idempotente. Só o workflow chama; o agente nunca (ADR 0007)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

ResultadoPublicacao = Literal["publicado", "ja_publicado", "dry_run"]


class PublicacaoEmAndamento(Exception):
    """Outra tentativa da mesma publicação está em curso; quem chama tenta de novo depois."""


class Publicador(Protocol):
    async def comentar(
        self, repositorio: str, numero: int, corpo: str, chave: str
    ) -> ResultadoPublicacao:
        """Comenta na issue no máximo uma vez por `chave`, mesmo com retentativas."""
        ...


@dataclass(frozen=True, slots=True)
class DestinoDaEntrega:
    """Onde a entrega escreve: a branch é derivada de (intent_id, slug), nunca informada."""

    repositorio: str
    intent_id: str
    slug: str


class PublicadorDeEntrega(Publicador, Protocol):
    async def commitar_artefato(
        self, destino: DestinoDaEntrega, nome: str, conteudo: str, mensagem: str
    ) -> ResultadoPublicacao: ...

    async def ler_artefato(self, destino: DestinoDaEntrega, nome: str) -> str | None: ...

    async def abrir_pr(self, destino: DestinoDaEntrega, titulo: str, corpo: str) -> str:
        """URL do PR; "dry-run" quando nada foi escrito."""
        ...


class RegistroIdempotencia(Protocol):
    async def reivindicar(self, chave: str) -> Literal["nova", "em_andamento", "concluida"]:
        """Atômico: só um chamador recebe "nova" para a mesma chave."""
        ...

    async def concluir(self, chave: str) -> None: ...

    async def liberar(self, chave: str) -> None:
        """Desfaz a reivindicação quando o efeito falhou, para a retentativa valer."""
        ...
