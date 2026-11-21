from __future__ import annotations

from typing import Protocol


class RegistroEntregas(Protocol):
    async def registrar_nova(self, entrega_id: str) -> bool:
        """True na primeira vez que o id é visto; False se repetido."""
        ...

    async def esquecer(self, entrega_id: str) -> None:
        """Desfaz o registro quando o processamento falhou, para o reenvio valer."""
        ...
