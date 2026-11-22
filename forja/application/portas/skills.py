from __future__ import annotations

from typing import Protocol


class FonteDeSkills(Protocol):
    async def nomes(self, repositorio: str) -> list[str]: ...

    async def ler(self, repositorio: str, nome: str) -> str | None: ...
