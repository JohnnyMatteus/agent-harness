"""Contexto Intake: a intenção de quem pediu, normalizada, com identidade determinística."""

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum

from forja.domain.erros import IntentInvalida, OrigemInvalida
from forja.domain.eventos import EventoDeDominio, IntentConfirmada, IntentRecebida


class TipoDeOrigem(StrEnum):
    ISSUE_GITHUB = "github"
    CLI = "cli"
    BANDA = "banda"


@dataclass(frozen=True, slots=True)
class Origem:
    """De onde a intenção veio. O trio (tipo, repositório, identificador) é a identidade."""

    tipo: TipoDeOrigem
    repositorio: str
    identificador: str
    titulo: str
    corpo: str = ""
    url: str | None = None

    def __post_init__(self) -> None:
        if not self.identificador.strip():
            raise OrigemInvalida("origem sem identificador")
        owner, _, nome = self.repositorio.partition("/")
        if not owner or not nome or "/" in nome:
            raise OrigemInvalida(f"repositório deve ser 'dono/nome': {self.repositorio!r}")
        if self.tipo is TipoDeOrigem.ISSUE_GITHUB and not (
            self.identificador.isascii()
            and self.identificador.isdigit()
            and int(self.identificador) > 0
        ):
            raise OrigemInvalida(f"número de issue inválido: {self.identificador!r}")
        if not self.titulo.strip():
            raise OrigemInvalida("origem sem título")

    @property
    def chave(self) -> str:
        return f"{self.tipo.value}:{self.repositorio.lower()}#{self.identificador.strip()}"


def intent_id_de(origem: Origem) -> str:
    """Id determinístico: 16 hex do SHA-256 da chave da origem (ADR 0030).

    Serve de nome de branch, pasta `.forja/<id>/` e id do workflow ("um workflow por intenção").
    """
    return hashlib.sha256(origem.chave.encode()).hexdigest()[:16]


@dataclass(slots=True)
class Intent:
    id: str
    origem: Origem
    criterios_de_sucesso: tuple[str, ...] = ()
    confirmada_por: str | None = None
    _eventos: list[EventoDeDominio] = field(default_factory=lambda: [], repr=False)

    @classmethod
    def receber(cls, origem: Origem, criterios_de_sucesso: tuple[str, ...] = ()) -> "Intent":
        if any(not c.strip() for c in criterios_de_sucesso):
            raise IntentInvalida("critério de sucesso vazio")
        intent = cls(
            id=intent_id_de(origem),
            origem=origem,
            criterios_de_sucesso=tuple(c.strip() for c in criterios_de_sucesso),
        )
        intent._eventos.append(IntentRecebida(intent_id=intent.id, origem=origem.chave))
        return intent

    @property
    def confirmada(self) -> bool:
        return self.confirmada_por is not None

    def confirmar(self, quem: str) -> None:
        """Quem pediu confirma o resumo. Idempotente: a segunda confirmação não emite evento."""
        if not quem.strip():
            raise IntentInvalida("confirmação precisa de quem confirmou")
        if self.confirmada:
            return
        self.confirmada_por = quem
        self._eventos.append(IntentConfirmada(intent_id=self.id, confirmado_por=quem))

    def retirar_eventos(self) -> list[EventoDeDominio]:
        eventos, self._eventos = self._eventos, []
        return eventos
