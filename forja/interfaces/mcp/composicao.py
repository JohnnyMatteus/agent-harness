"""Composição do servidor MCP knowledge a partir do ambiente (um processo por sessão)."""

from __future__ import annotations

from collections.abc import Mapping

from mcp.server.mcpserver import MCPServer

from forja.application.casos_de_uso.obter_simbolo import ObterSimbolo
from forja.application.casos_de_uso.recuperar_conhecimento import RecuperarConhecimento
from forja.application.portas.knowledge import IndiceDeTrechos
from forja.infrastructure.knowledge.configuracao import (
    VARIAVEL_BANCO,
    ConfiguracaoInvalida,
    embedder_do_ambiente,
    exigir,
)
from forja.infrastructure.knowledge.postgres import IndicePostgres
from forja.infrastructure.knowledge.token_sessao import TokenInvalido, verificar_token
from forja.interfaces.mcp.knowledge import criar_servidor

VARIAVEL_TOKEN = "FORJA_KNOWLEDGE_TOKEN"
VARIAVEL_SEGREDO = "FORJA_KNOWLEDGE_TOKEN_SECRET"


def servidor_do_ambiente(
    ambiente: Mapping[str, str], indice: IndiceDeTrechos | None = None
) -> MCPServer:
    try:
        escopo = verificar_token(
            exigir(ambiente, VARIAVEL_TOKEN), exigir(ambiente, VARIAVEL_SEGREDO)
        )
    except (TokenInvalido, ValueError) as erro:
        raise ConfiguracaoInvalida("token de sessao invalido ou segredo fraco") from erro
    embedder = embedder_do_ambiente(ambiente)
    indice = indice or IndicePostgres(exigir(ambiente, VARIAVEL_BANCO))
    return criar_servidor(RecuperarConhecimento(indice, embedder), ObterSimbolo(indice), escopo)
