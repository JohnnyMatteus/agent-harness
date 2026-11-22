"""Adaptador da porta `PesquisaDeConhecimento` sobre o RAG do M2.

O escopo (organização, repositório) sai do repositório da entrega, nunca do texto do modelo.
O MCP knowledge, que guarda o segredo dos tokens, não participa daqui: a busca é por código
no worker, e o agente só recebe os trechos.
"""

from __future__ import annotations

import asyncio

from forja.application.casos_de_uso.recuperar_conhecimento import RecuperarConhecimento
from forja.application.portas.sdlc import FonteRecuperada
from forja.domain.knowledge import Escopo, Filtro, TipoDeTrecho
from forja.domain.seguranca import repositorio_valido


class SemPesquisa:
    """RAG não configurado: devolve vazio, e a spec sai sem fontes (e diz isso)."""

    async def pesquisar(
        self, repositorio: str, consulta: str, tipo: str | None, k: int
    ) -> list[FonteRecuperada]:
        return []


class PesquisaRag:
    def __init__(self, recuperar: RecuperarConhecimento) -> None:
        self._recuperar = recuperar

    async def pesquisar(
        self, repositorio: str, consulta: str, tipo: str | None, k: int
    ) -> list[FonteRecuperada]:
        if not repositorio_valido(repositorio):
            raise ValueError("repositório inválido")
        org, _, nome = repositorio.partition("/")
        filtro = Filtro(tipos=frozenset({TipoDeTrecho(tipo)}) if tipo else None)
        pagina = await asyncio.to_thread(
            self._recuperar.buscar, Escopo(org, nome), consulta, limite=k, filtro=filtro
        )
        return [
            FonteRecuperada(
                r.trecho.id,
                r.trecho.caminho,
                r.trecho.commit,
                r.trecho.tipo.value,
                r.trecho.conteudo,
            )
            for r in pagina.itens
        ]
