from __future__ import annotations

from typing import Protocol


class GitHubPort(Protocol):
    """Escritas mínimas do M1; só o workflow chama, nunca o agente (ADR 0007)."""

    async def comentar_issue(self, repositorio: str, numero: int, corpo: str) -> None: ...

    async def criar_branch(self, repositorio: str, intent_id: str, slug: str) -> str:
        """Cria `forja/<intent-id>-<slug>` a partir da branch padrão e devolve o nome."""
        ...
