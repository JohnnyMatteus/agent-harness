"""Porta do sandbox efêmero por sessão (ADRs 0008/0016, seção 9.4 do design doc)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


class SandboxError(Exception):
    """Falha ao criar, executar ou destruir um sandbox."""


@dataclass(frozen=True)
class EspecSandbox:
    sessao_id: str
    repo_url: str
    ref: str = "HEAD"
    # Segredos só entram aqui de propósito, para um passo de teste; nunca herdados do host.
    ambiente_injetado: dict[str, str] = field(default_factory=dict[str, str])


@dataclass(frozen=True)
class ResultadoComando:
    codigo_saida: int
    stdout: str
    stderr: str


class SandboxAtivo(Protocol):
    @property
    def sessao_id(self) -> str: ...

    @property
    def worktree(self) -> Path:
        """Diretório de trabalho do agente dentro do sandbox."""
        ...

    async def executar(self, comando: list[str], timeout_s: float = 60.0) -> ResultadoComando: ...


class Sandbox(Protocol):
    async def criar(self, spec: EspecSandbox) -> SandboxAtivo: ...

    async def destruir(self, sessao_id: str) -> None:
        """Idempotente: destrói container e worktree; chamado também por /forja stop."""
