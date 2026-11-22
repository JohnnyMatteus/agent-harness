"""Lista os arquivos versionados de um clone local, só os caminhos, sem executar nada do repo."""

from __future__ import annotations

import asyncio

from forja.domain.artefatos import ArtefatoInvalido, caminho_relativo_seguro
from forja.infrastructure.sandbox.repositorios import RepositoriosLocais


class ListadorGit:
    def __init__(self, repos: RepositoriosLocais) -> None:
        self._repos = repos

    async def listar(self, repositorio: str) -> tuple[str, ...]:
        raiz = self._repos.caminho(repositorio)
        # Sem fsmonitor nem hooks: o clone é conteúdo não confiável.
        proc = await asyncio.create_subprocess_exec(
            "git", "-c", "core.fsmonitor=false", "-C", raiz, "ls-files", "-z",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )  # fmt: skip
        saida, _ = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError("git ls-files falhou")
        caminhos: list[str] = []
        for nome in saida.decode(errors="replace").split("\0"):
            try:
                caminhos.append(caminho_relativo_seguro(nome))
            except ArtefatoInvalido:
                continue  # nome estranho no repo: não vai para o prompt
        return tuple(caminhos)
