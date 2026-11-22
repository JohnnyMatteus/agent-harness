from __future__ import annotations

import hashlib
import logging

from forja.application.portas.github import GitHubPort
from forja.application.portas.publicador import (
    DestinoDaEntrega,
    PublicacaoEmAndamento,
    RegistroIdempotencia,
    ResultadoPublicacao,
)
from forja.domain.artefatos import (
    caminho_do_artefato,
    intent_id_valido,
    linha_unica,
)
from forja.domain.seguranca import neutralizar_texto, repositorio_valido
from forja.infrastructure.github.cliente import nome_da_branch

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

    def _branch(self, destino: DestinoDaEntrega) -> str:
        if not repositorio_valido(destino.repositorio) or not intent_id_valido(destino.intent_id):
            raise ValueError("destino de publicação inválido")
        return nome_da_branch(destino.intent_id, destino.slug)

    async def commitar_artefato(
        self, destino: DestinoDaEntrega, nome: str, conteudo: str, mensagem: str
    ) -> ResultadoPublicacao:
        """Commita `.forja/<id>/<nome>` na branch da entrega. A mensagem é montada pelo chamador
        (trailers incluídos); o conteúdo é o artefato renderizado por código."""
        branch = self._branch(destino)
        caminho = caminho_do_artefato(destino.intent_id, nome)
        if self._dry_run:
            log.info("dry-run: artefato não commitado", extra={"caminho": caminho})
            return "dry_run"
        digest = hashlib.sha256(conteudo.encode()).hexdigest()[:16]
        chave = f"{destino.intent_id}:commit:{nome}:{digest}"
        estado = await self._registro.reivindicar(chave)
        if estado == "concluida":
            return "ja_publicado"
        if estado == "em_andamento":
            raise PublicacaoEmAndamento(chave)
        try:
            await self._github.criar_branch(destino.repositorio, destino.intent_id, destino.slug)
            await self._github.commitar_arquivo(
                destino.repositorio, branch, caminho, conteudo, linha_unica(mensagem, 2000)
            )
        except BaseException:
            await self._registro.liberar(chave)
            raise
        await self._registro.concluir(chave)
        return "publicado"

    async def ler_artefato(self, destino: DestinoDaEntrega, nome: str) -> str | None:
        """Versão da branch (pode ter sido editada por um humano); None sem branch ou em dry-run."""
        branch = self._branch(destino)
        if self._dry_run:
            return None
        caminho = caminho_do_artefato(destino.intent_id, nome)
        try:
            return await self._github.ler_arquivo(destino.repositorio, branch, caminho)
        except Exception:
            log.warning("não foi possível ler o artefato da branch", extra={"caminho": caminho})
            return None

    async def abrir_pr(self, destino: DestinoDaEntrega, titulo: str, corpo: str) -> str:
        branch = self._branch(destino)
        if self._dry_run:
            log.info("dry-run: PR não aberto", extra={"branch": branch})
            return "dry-run"
        chave = f"{destino.intent_id}:pr"
        estado = await self._registro.reivindicar(chave)
        if estado == "em_andamento":
            raise PublicacaoEmAndamento(chave)
        # O GitHub é a fonte da verdade: abrir_pr devolve o PR que já existe.
        try:
            url = await self._github.abrir_pr(
                destino.repositorio,
                branch,
                linha_unica(neutralizar_texto(titulo, 200), 200),
                neutralizar_texto(corpo, 20_000),
                rascunho=True,
            )
        except BaseException:
            if estado == "nova":
                await self._registro.liberar(chave)
            raise
        await self._registro.concluir(chave)
        return url
