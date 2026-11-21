from __future__ import annotations

from typing import Protocol


class VerificadorPermissao(Protocol):
    async def tem_escrita(self, repositorio: str, usuario: str) -> bool: ...
