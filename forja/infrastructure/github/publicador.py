from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Awaitable, Callable, Sequence

from forja.application.portas.github import GitHubPort
from forja.application.portas.publicador import (
    DestinoDaEntrega,
    PublicacaoEmAndamento,
    RegistroIdempotencia,
    ResultadoPublicacao,
)
from forja.application.portas.revisao import ClienteDeRevisao
from forja.domain.artefatos import (
    caminho_do_artefato,
    intent_id_valido,
    linha_unica,
    sanear_mensagem_de_commit,
)
from forja.domain.incidente import ROTULO_DO_INCIDENTE
from forja.domain.revisao import Achado, Severidade
from forja.domain.seguranca import neutralizar_texto, repositorio_valido
from forja.infrastructure.github.cliente import nome_da_branch

log = logging.getLogger(__name__)


class PublicadorGitHub:
    """Único caminho de escrita no GitHub. Dry-run por padrão: sem `dry_run=False` explícito
    nada é escrito. Todo corpo é neutralizado aqui, no ponto de saída."""

    def __init__(
        self,
        github: GitHubPort,
        registro: RegistroIdempotencia,
        *,
        dry_run: bool = True,
        revisao: ClienteDeRevisao | None = None,
    ) -> None:
        self._revisao = revisao
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
                destino.repositorio, branch, caminho, conteudo, sanear_mensagem_de_commit(mensagem)
            )
        except BaseException:
            await self._registro.liberar(chave)
            raise
        await self._registro.concluir(chave)
        return "publicado"

    async def ler_artefato(self, destino: DestinoDaEntrega, nome: str) -> str | None:
        """Versão da branch (pode ter sido editada por um humano); None só se não existe (ou
        em dry-run)."""
        branch = self._branch(destino)
        if self._dry_run:
            return None
        caminho = caminho_do_artefato(destino.intent_id, nome)
        # Falha fechada: só a ausência (None) é ausência; erro do GitHub sobe e o Temporal retenta.
        return await self._github.ler_arquivo(destino.repositorio, branch, caminho)

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

    # --- revisão e deploy (M5) --------------------------------------------------------

    async def _uma_vez(
        self, chave: str, acao: Callable[[], Awaitable[None]]
    ) -> ResultadoPublicacao:
        estado = await self._registro.reivindicar(chave)
        if estado == "concluida":
            return "ja_publicado"
        if estado == "em_andamento":
            raise PublicacaoEmAndamento(chave)
        try:
            await acao()
        except BaseException:
            await self._registro.liberar(chave)
            raise
        await self._registro.concluir(chave)
        return "publicado"

    def _cliente(self) -> ClienteDeRevisao:
        if self._revisao is None:
            raise RuntimeError("cliente de revisão não configurado")
        return self._revisao

    async def check_run(
        self,
        repositorio: str,
        head_sha: str,
        nome: str,
        achados: Sequence[Achado],
        resumo: str,
        chave: str,
    ) -> str:
        if not repositorio_valido(repositorio) or not re.fullmatch(r"[0-9a-f]{40}", head_sha):
            raise ValueError("destino de check run inválido")
        bloqueante = any(a.severidade is Severidade.BLOQUEANTE for a in achados)
        conclusao = "failure" if bloqueante else ("neutral" if achados else "success")
        anotacoes = [
            {
                "path": a.arquivo,
                "start_line": a.linha or 1,
                "end_line": a.linha or 1,
                "annotation_level": "failure"
                if a.severidade is Severidade.BLOQUEANTE
                else "warning",
                "message": neutralizar_texto(a.mensagem, 500),
            }
            for a in achados
            if a.arquivo
        ]
        if self._dry_run:
            log.info("dry-run: check run não criado", extra={"nome": nome, "conclusao": conclusao})
            return "dry_run"
        await self._uma_vez(
            f"{chave}:check:{nome}:{head_sha}",
            lambda: self._cliente().criar_check_run(
                repositorio,
                head_sha,
                f"forja/{nome}",
                conclusao,
                f"Forja: revisão de {nome}",
                neutralizar_texto(resumo, 4000),
                anotacoes,
            ),
        )
        return conclusao

    async def marcar_pr_pronto(self, repositorio: str, numero: int, chave: str) -> str:
        if not repositorio_valido(repositorio) or numero < 1:
            raise ValueError("destino inválido")
        if self._dry_run:
            return "dry_run"
        return await self._uma_vez(
            f"{chave}:pronto:{numero}",
            lambda: self._cliente().marcar_pr_pronto(repositorio, numero),
        )

    async def mesclar_pr(self, repositorio: str, numero: int, sha: str, chave: str) -> str:
        if (
            not repositorio_valido(repositorio)
            or numero < 1
            or not re.fullmatch(r"[0-9a-f]{40}", sha)
        ):
            raise ValueError("destino de merge inválido")
        if self._dry_run:
            log.info("dry-run: merge não feito", extra={"repositorio": repositorio, "pr": numero})
            return "dry_run"
        return await self._uma_vez(
            f"{chave}:merge:{numero}:{sha}",
            lambda: self._cliente().mesclar_pr(repositorio, numero, sha),
        )

    async def abrir(self, repositorio: str, titulo: str, corpo: str, chave: str) -> str:
        """Issue do incidente, uma vez por `chave`, com o label `forja:incident` (nunca
        `forja:intent`: quem aplica este é um humano, no portão). Dry-run por padrão."""
        if not repositorio_valido(repositorio):
            raise ValueError("destino inválido")
        if self._dry_run:
            log.info("dry-run: issue de incidente não aberta", extra={"chave": chave})
            return "dry-run"
        titulo_unico = linha_unica(neutralizar_texto(titulo, 150), 150)
        try:
            abertas = await self._cliente().titulos_de_issues_abertas(
                repositorio, ROTULO_DO_INCIDENTE
            )
        except Exception:
            log.warning("incidente não aberto: não foi possível listar as issues abertas")
            return "nao_aberta (lista de issues indisponivel)"
        if titulo_unico in abertas:
            return "nao_aberta (ja ha issue de incidente aberta para a banda)"
        url: list[str] = []

        async def abrir() -> None:
            url.append(
                await self._cliente().criar_issue(
                    repositorio,
                    titulo_unico,
                    neutralizar_texto(corpo, 8000),
                    [ROTULO_DO_INCIDENTE],
                )
            )

        resultado = await self._uma_vez(f"incidente:{chave}", abrir)
        return url[0] if url else f"ja_aberta ({resultado})"
