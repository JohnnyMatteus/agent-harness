"""Resolve `dono/nome` para um clone local previamente preparado pelo operador.

O nome vem de um webhook (não confiável): é validado e o caminho final precisa ficar
dentro da raiz configurada, sem seguir symlink para fora.
"""

from __future__ import annotations

from pathlib import Path

from forja.application.portas.sandbox import SandboxError
from forja.domain.seguranca import repositorio_valido


class RepositoriosLocais:
    def __init__(self, raiz: Path) -> None:
        self._raiz = raiz.resolve()

    def caminho(self, repositorio: str) -> str:
        if not repositorio_valido(repositorio):
            raise SandboxError("nome de repositório inválido")
        destino = (self._raiz / repositorio).resolve()
        if not destino.is_relative_to(self._raiz) or not (destino / ".git").exists():
            raise SandboxError(f"clone local ausente ou fora da raiz para {repositorio}")
        return str(destino)
