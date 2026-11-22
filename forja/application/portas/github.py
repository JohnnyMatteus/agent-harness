from __future__ import annotations

from typing import Protocol


class GitHubPort(Protocol):
    """Escritas mínimas do M1; só o workflow chama, nunca o agente (ADR 0007)."""

    async def comentar_issue(self, repositorio: str, numero: int, corpo: str) -> None: ...

    async def criar_branch(self, repositorio: str, intent_id: str, slug: str) -> str:
        """Cria `forja/<intent-id>-<slug>` a partir da branch padrão e devolve o nome."""
        ...

    async def commitar_arquivo(
        self, repositorio: str, branch: str, caminho: str, conteudo: str, mensagem: str
    ) -> bool:
        """Cria ou atualiza um arquivo na branch da entrega; False se já tinha o mesmo conteúdo."""
        ...

    async def ler_arquivo(self, repositorio: str, branch: str, caminho: str) -> str | None: ...

    async def abrir_pr(
        self, repositorio: str, branch: str, titulo: str, corpo: str, rascunho: bool
    ) -> str:
        """Abre o PR da branch ou devolve a URL do que já existe (idempotente)."""
        ...
