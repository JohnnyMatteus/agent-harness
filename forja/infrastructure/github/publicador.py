from __future__ import annotations

import logging

from forja.application.portas.github import GitHubPort
from forja.application.portas.publicador import (
    PublicacaoEmAndamento,
    RegistroIdempotencia,
    ResultadoPublicacao,
)
from forja.domain.seguranca import neutralizar_texto, repositorio_valido

log = logging.getLogger(__name__)


class PublicadorGitHub:
    """Único caminho de escrita no GitHub. Dry-run por padrão: sem `dry_run=False` explícito
    nada é escrito. Todo corpo é neutralizado aqui, no ponto de saída."""

    def __init__(
        self, github: GitHubPort, registro: RegistroIdempotencia, *, dry_run: bool = True
    ) -> None:
        self._github = github
        self._registro = registro
        self._dry_run = dry_run

    async def comentar(
        self, repositorio: str, numero: int, corpo: str, chave: str
    ) -> ResultadoPublicacao:
        if not repositorio_valido(repositorio) or numero < 1:
            raise ValueError("destino de publicação inválido")
        texto = neutralizar_texto(corpo)
        if self._dry_run:
            log.info(
                "dry-run: comentário não publicado",
                extra={"repositorio": repositorio, "numero": numero, "chave": chave},
            )
            return "dry_run"
        estado = await self._registro.reivindicar(chave)
        if estado == "concluida":
            return "ja_publicado"
        if estado == "em_andamento":
            raise PublicacaoEmAndamento(chave)
        try:
            await self._github.comentar_issue(repositorio, numero, texto)
        except BaseException:
            await self._registro.liberar(chave)
            raise
        await self._registro.concluir(chave)
        return "publicado"
