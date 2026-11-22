from __future__ import annotations

from typing import Protocol


class ArmazemDeMemoria(Protocol):
    """Arquivos curtos por repositório. O `repositorio` é sempre dado pelo workflow."""

    async def listar(self, repositorio: str) -> dict[str, int]:
        """Caminho relativo -> tamanho em bytes."""
        ...

    async def ler(self, repositorio: str, caminho: str) -> str | None: ...

    async def gravar(self, repositorio: str, caminho: str, conteudo: str) -> None: ...

    async def apagar(self, repositorio: str, caminho: str) -> bool: ...
