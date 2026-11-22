"""Armazéns da memória por repositório: em memória (testes) e Postgres (produção).

O Postgres não foi exercitado contra um servidor real fora do teste de integração do CI.
"""

from __future__ import annotations

import asyncio

import psycopg

ESQUEMA = """CREATE TABLE IF NOT EXISTS memoria_repositorio (
    repositorio text NOT NULL,
    caminho text NOT NULL,
    conteudo text NOT NULL,
    atualizado timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (repositorio, caminho))"""


class ArmazemEmMemoria:
    def __init__(self) -> None:
        self._dados: dict[tuple[str, str], str] = {}

    async def listar(self, repositorio: str) -> dict[str, int]:
        return {c: len(t.encode()) for (r, c), t in self._dados.items() if r == repositorio}

    async def ler(self, repositorio: str, caminho: str) -> str | None:
        return self._dados.get((repositorio, caminho))

    async def gravar(self, repositorio: str, caminho: str, conteudo: str) -> None:
        self._dados[(repositorio, caminho)] = conteudo

    async def apagar(self, repositorio: str, caminho: str) -> bool:
        return self._dados.pop((repositorio, caminho), None) is not None


class ArmazemPostgres:
    def __init__(self, url: str) -> None:
        self._url = url

    def garantir_esquema(self) -> None:
        with psycopg.connect(self._url) as con:
            con.execute(ESQUEMA)

    async def listar(self, repositorio: str) -> dict[str, int]:
        return await asyncio.to_thread(self._listar, repositorio)

    def _listar(self, repositorio: str) -> dict[str, int]:
        with psycopg.connect(self._url) as con:
            linhas = con.execute(
                "SELECT caminho, octet_length(conteudo) FROM memoria_repositorio "
                "WHERE repositorio = %s",
                (repositorio,),
            ).fetchall()
        return {str(c): int(n) for c, n in linhas}

    async def ler(self, repositorio: str, caminho: str) -> str | None:
        return await asyncio.to_thread(self._ler, repositorio, caminho)

    def _ler(self, repositorio: str, caminho: str) -> str | None:
        with psycopg.connect(self._url) as con:
            linha = con.execute(
                "SELECT conteudo FROM memoria_repositorio WHERE repositorio = %s AND caminho = %s",
                (repositorio, caminho),
            ).fetchone()
        return None if linha is None else str(linha[0])

    async def gravar(self, repositorio: str, caminho: str, conteudo: str) -> None:
        await asyncio.to_thread(self._gravar, repositorio, caminho, conteudo)

    def _gravar(self, repositorio: str, caminho: str, conteudo: str) -> None:
        with psycopg.connect(self._url) as con:
            con.execute(
                "INSERT INTO memoria_repositorio (repositorio, caminho, conteudo) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT (repositorio, caminho) DO UPDATE SET conteudo = EXCLUDED.conteudo, "
                "atualizado = now()",
                (repositorio, caminho, conteudo),
            )

    async def apagar(self, repositorio: str, caminho: str) -> bool:
        return await asyncio.to_thread(self._apagar, repositorio, caminho)

    def _apagar(self, repositorio: str, caminho: str) -> bool:
        with psycopg.connect(self._url) as con:
            return (
                con.execute(
                    "DELETE FROM memoria_repositorio WHERE repositorio = %s AND caminho = %s",
                    (repositorio, caminho),
                ).rowcount
                > 0
            )
