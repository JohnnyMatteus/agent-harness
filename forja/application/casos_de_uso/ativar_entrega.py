from __future__ import annotations

import logging

from forja.application.comandos import Comando, CriarIntent, Ignorado, ResultadoAtivacao, Traducao
from forja.application.portas.entregas import EntregaGateway
from forja.application.portas.permissoes import VerificadorPermissao
from forja.domain.seguranca import repositorio_valido

log = logging.getLogger(__name__)


class AtivarEntrega:
    """Do webhook ao workflow: só quem tem escrita no repositório aciona agentes (seção 7)."""

    def __init__(
        self,
        entregas: EntregaGateway,
        permissoes: VerificadorPermissao,
        repositorios_habilitados: frozenset[str] | None = None,
    ) -> None:
        """`repositorios_habilitados=None` não restringe; vazio recusa tudo (falha fechada)."""
        self._entregas = entregas
        self._permissoes = permissoes
        self._habilitados = (
            None
            if repositorios_habilitados is None
            else frozenset(r.lower() for r in repositorios_habilitados)
        )

    async def executar(self, traducao: Traducao) -> ResultadoAtivacao:
        if isinstance(traducao, Ignorado):
            log.info("evento ignorado", extra={"motivo": traducao.motivo})
            return "ignorada"
        repositorio = traducao.origem.repositorio
        if not repositorio_valido(repositorio) or (
            self._habilitados is not None and repositorio.lower() not in self._habilitados
        ):
            log.warning("repositório não habilitado; evento ignorado", extra={"repo": repositorio})
            return "ignorada"
        if not await self._autorizado(traducao):
            log.warning(
                "autor sem permissão de escrita; evento ignorado",
                extra={"repositorio": traducao.origem.repositorio, "autor": traducao.autor},
            )
            return "ignorada"
        if isinstance(traducao, CriarIntent):
            return await self._entregas.iniciar(traducao)
        return "sinalizada" if await self._entregas.parar(traducao.origem) else "ignorada"

    async def _autorizado(self, comando: Comando) -> bool:
        return await self._permissoes.tem_escrita(comando.origem.repositorio, comando.autor)
