from __future__ import annotations

from typing import Literal, Protocol

from forja.application.comandos import CriarIntent, OrigemExterna, Sinalizacao

ResultadoInicio = Literal["iniciada", "ja_existia"]


class EntregaGateway(Protocol):
    """Porta para o orquestrador durável (Temporal, em M1-07).

    Um workflow por Intent: iniciar de novo vira sinal, nunca execução duplicada.
    """

    async def iniciar(self, comando: CriarIntent) -> ResultadoInicio: ...

    async def parar(self, origem: OrigemExterna) -> bool:
        """Sinaliza "parar"; False quando não há entrega em andamento."""
        ...

    async def sinalizar(self, comando: Sinalizacao) -> bool:
        """Entrega confirmação, aprovação ou rejeição; False quando não há entrega."""
        ...

    async def cancelar_todas(self) -> int:
        """Cancela todas as entregas e destrói seus sandboxes; devolve quantas."""
        ...
