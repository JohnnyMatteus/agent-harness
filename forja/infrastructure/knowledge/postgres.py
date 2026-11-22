"""Índice híbrido em PostgreSQL + pgvector (HNSW) + busca textual nativa.

Requer pgvector 0.8 ou superior (`hnsw.iterative_scan`, para o filtro por escopo não esvaziar o
resultado do HNSW). Não foi exercitado contra um Postgres real fora do teste de integração
(`pytest -m integration`), que sobe um contêiner via testcontainers.

A busca textual usa `ts_rank_cd` sobre `tsvector`: é uma aproximação de BM25, não BM25 (ADR 0051).
Toda consulta leva `organizacao` e `repositorio` no WHERE.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import psycopg

from forja.domain.knowledge import Escopo, Filtro, TipoDeTrecho, Trecho
from forja.infrastructure.knowledge.texto import termos, texto_de_busca

_COLUNAS = (
    "id, caminho, linguagem, tipo, simbolo, linha_inicio, linha_fim, conteudo, contexto, commit_sha"
)
_FILTROS = (
    "organizacao = %(org)s AND repositorio = %(repo)s "
    "AND (%(tipos)s::text[] IS NULL OR tipo = ANY(%(tipos)s::text[])) "
    "AND (%(lang)s::text IS NULL OR linguagem = %(lang)s::text)"
)


def esquema(dimensao: int) -> list[str]:
    return [
        "CREATE EXTENSION IF NOT EXISTS vector",
        """CREATE TABLE IF NOT EXISTS knowledge_arquivo (
            organizacao text NOT NULL,
            repositorio text NOT NULL,
            caminho text NOT NULL,
            versao text NOT NULL,
            PRIMARY KEY (organizacao, repositorio, caminho))""",
        f"""CREATE TABLE IF NOT EXISTS knowledge_trecho (
            organizacao text NOT NULL,
            repositorio text NOT NULL,
            id text NOT NULL,
            caminho text NOT NULL,
            linguagem text NOT NULL,
            tipo text NOT NULL,
            simbolo text,
            linha_inicio integer NOT NULL,
            linha_fim integer NOT NULL,
            conteudo text NOT NULL,
            contexto text NOT NULL,
            commit_sha text NOT NULL,
            busca text NOT NULL,
            tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', busca)) STORED,
            embedding vector({int(dimensao)}) NOT NULL,
            PRIMARY KEY (organizacao, repositorio, id))""",
        "CREATE INDEX IF NOT EXISTS knowledge_trecho_tsv ON knowledge_trecho USING gin (tsv)",
        "CREATE INDEX IF NOT EXISTS knowledge_trecho_hnsw "
        "ON knowledge_trecho USING hnsw (embedding vector_cosine_ops)",
        "CREATE INDEX IF NOT EXISTS knowledge_trecho_simbolo "
        "ON knowledge_trecho (organizacao, repositorio, caminho, simbolo)",
    ]


def _literal_vetor(vetor: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vetor) + "]"


def _trecho(escopo: Escopo, linha: tuple[Any, ...]) -> Trecho:
    return Trecho(
        id=linha[0],
        escopo=escopo,
        caminho=linha[1],
        linguagem=linha[2],
        tipo=TipoDeTrecho(linha[3]),
        simbolo=linha[4],
        linha_inicio=linha[5],
        linha_fim=linha[6],
        conteudo=linha[7],
        contexto=linha[8],
        commit=linha[9],
    )


def _parametros_de_filtro(escopo: Escopo, filtro: Filtro) -> dict[str, Any]:
    return {
        "org": escopo.organizacao,
        "repo": escopo.repositorio,
        "tipos": None if filtro.tipos is None else sorted(t.value for t in filtro.tipos),
        "lang": filtro.linguagem,
    }


class IndicePostgres:
    """Uma conexão por operação: simples e seguro entre threads; o pool fica para a carga real."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def garantir_esquema(self, dimensao: int) -> None:
        with psycopg.connect(self._dsn) as conexao:
            for comando in esquema(dimensao):
                conexao.execute(comando.encode())

    def versoes_por_arquivo(self, escopo: Escopo) -> dict[str, str]:
        with psycopg.connect(self._dsn) as conexao:
            linhas = conexao.execute(
                "SELECT caminho, versao FROM knowledge_arquivo "
                "WHERE organizacao = %s AND repositorio = %s",
                (escopo.organizacao, escopo.repositorio),
            ).fetchall()
        return {c: v for c, v in linhas}

    def substituir_arquivo(
        self,
        escopo: Escopo,
        caminho: str,
        versao: str,
        itens: Sequence[tuple[Trecho, Sequence[float]]],
    ) -> None:
        for trecho, _ in itens:
            if trecho.escopo != escopo or trecho.caminho != caminho:
                raise ValueError("trecho fora do escopo ou do caminho informado")
        chave = (escopo.organizacao, escopo.repositorio, caminho)
        with psycopg.connect(self._dsn) as conexao, conexao.cursor() as cursor:
            cursor.execute(
                "DELETE FROM knowledge_trecho "
                "WHERE organizacao = %s AND repositorio = %s AND caminho = %s",
                chave,
            )
            cursor.executemany(
                "INSERT INTO knowledge_trecho (organizacao, repositorio, id, caminho, linguagem, "
                "tipo, simbolo, linha_inicio, linha_fim, conteudo, contexto, commit_sha, busca, "
                "embedding) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                "%s::vector)",
                [
                    (
                        escopo.organizacao,
                        escopo.repositorio,
                        t.id,
                        t.caminho,
                        t.linguagem,
                        t.tipo.value,
                        t.simbolo,
                        t.linha_inicio,
                        t.linha_fim,
                        t.conteudo,
                        t.contexto,
                        t.commit,
                        texto_de_busca(t.texto_indexado),
                        _literal_vetor(v),
                    )
                    for t, v in itens
                ],
            )
            cursor.execute(
                "INSERT INTO knowledge_arquivo (organizacao, repositorio, caminho, versao) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (organizacao, repositorio, caminho) "
                "DO UPDATE SET versao = EXCLUDED.versao",
                (*chave, versao),
            )

    def remover_arquivo(self, escopo: Escopo, caminho: str) -> None:
        chave = (escopo.organizacao, escopo.repositorio, caminho)
        with psycopg.connect(self._dsn) as conexao:
            for tabela in ("knowledge_trecho", "knowledge_arquivo"):
                conexao.execute(
                    f"DELETE FROM {tabela} "
                    "WHERE organizacao = %s AND repositorio = %s AND caminho = %s",
                    chave,
                )

    def buscar_lexical(
        self, escopo: Escopo, consulta: str, limite: int, filtro: Filtro
    ) -> list[Trecho]:
        # Só [a-z0-9] chega ao tsquery: sem operadores, sem injeção de sintaxe.
        tokens = sorted(set(termos(consulta)))
        if not tokens:
            return []
        with psycopg.connect(self._dsn) as conexao:
            linhas = conexao.execute(
                f"SELECT {_COLUNAS} FROM knowledge_trecho, "
                "to_tsquery('simple', %(q)s) AS q "
                f"WHERE {_FILTROS} AND tsv @@ q "
                "ORDER BY ts_rank_cd(tsv, q, 1) DESC, id LIMIT %(lim)s",
                {**_parametros_de_filtro(escopo, filtro), "q": " | ".join(tokens), "lim": limite},
            ).fetchall()
        return [_trecho(escopo, linha) for linha in linhas]

    def buscar_vetorial(
        self, escopo: Escopo, vetor: Sequence[float], limite: int, filtro: Filtro
    ) -> list[Trecho]:
        with psycopg.connect(self._dsn) as conexao, conexao.transaction():
            conexao.execute("SET LOCAL hnsw.iterative_scan = strict_order")
            linhas = conexao.execute(
                f"SELECT {_COLUNAS} FROM knowledge_trecho "
                f"WHERE {_FILTROS} "
                "ORDER BY embedding <=> %(v)s::vector, id LIMIT %(lim)s",
                {
                    **_parametros_de_filtro(escopo, filtro),
                    "v": _literal_vetor(vetor),
                    "lim": limite,
                },
            ).fetchall()
        return [_trecho(escopo, linha) for linha in linhas]

    def obter_simbolo(self, escopo: Escopo, caminho: str, simbolo: str) -> list[Trecho]:
        with psycopg.connect(self._dsn) as conexao:
            linhas = conexao.execute(
                f"SELECT {_COLUNAS} FROM knowledge_trecho "
                "WHERE organizacao = %s AND repositorio = %s AND caminho = %s AND simbolo = %s "
                "ORDER BY linha_inicio",
                (escopo.organizacao, escopo.repositorio, caminho, simbolo),
            ).fetchall()
        return [_trecho(escopo, linha) for linha in linhas]
