"""Operações de git sobre o worktree, feitas pelo workflow e nunca pelo agente."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from forja.domain.guardrails import MudancaDeArquivo


class AreaDeTrabalho(Protocol):
    async def ler(self, worktree: Path, caminho: str) -> str | None: ...

    async def escrever(self, worktree: Path, caminho: str, conteudo: str) -> None: ...

    async def head(self, worktree: Path) -> str: ...

    async def garantir_branch(self, worktree: Path, branch: str) -> None:
        """Deixa o worktree na branch da entrega (criando-a a partir do HEAD se preciso)."""
        ...

    async def mudancas(self, worktree: Path, base: str) -> list[MudancaDeArquivo]:
        """O que a sessão mudou em relação a `base`, incluindo arquivos não commitados."""
        ...

    async def descartar(self, worktree: Path, base: str) -> None:
        """Volta o worktree a `base`, apagando tudo que a sessão criou."""
        ...

    async def commitar(self, worktree: Path, mensagem: str) -> str | None:
        """Commit de tudo que mudou; None se não havia nada."""
        ...

    async def log_recente(self, worktree: Path, quantos: int) -> str: ...

    async def arquivos_de_teste_e_links(
        self, worktree: Path
    ) -> tuple[frozenset[str], frozenset[str]]:
        """(testes existentes, links simbólicos) do worktree; levanta se um link sai dele."""
        ...


class RemotoGit(Protocol):
    async def buscar(self, repositorio: str, branch: str, worktree: Path) -> bool:
        """Traz a branch da entrega para o worktree; False se ela ainda não existe no remoto."""
        ...

    async def enviar(self, repositorio: str, branch: str, worktree: Path) -> None:
        """Publica a branch da entrega (nunca a padrão, nunca com force)."""
        ...
