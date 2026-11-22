"""Portas de saída para persistir agregados e publicar eventos de domínio."""

from collections.abc import Sequence
from typing import Protocol

from forja.domain.entrega import Entrega
from forja.domain.eventos import EventoDeDominio
from forja.domain.intent import Intent


class RepositorioDeIntents(Protocol):
    async def obter(self, intent_id: str) -> Intent | None: ...

    async def salvar(self, intent: Intent) -> None: ...


class RepositorioDeEntregas(Protocol):
    async def obter(self, intent_id: str) -> Entrega | None: ...

    async def salvar(self, entrega: Entrega) -> None: ...


class PublicadorDeEventos(Protocol):
    async def publicar(self, eventos: Sequence[EventoDeDominio]) -> None: ...
