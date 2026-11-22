"""Memória por repositório em Postgres real (contêiner); roda só no CI: `pytest -m integration`."""

from collections.abc import Iterator

import pytest
from testcontainers.community.postgres import PostgresContainer

from forja.application.casos_de_uso.memoria_do_repositorio import MemoriaDoRepositorio
from forja.infrastructure.persistencia.memoria import ArmazemPostgres

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="function")]


@pytest.fixture(scope="module")
def armazem() -> Iterator[ArmazemPostgres]:
    with PostgresContainer("pgvector/pgvector:pg16", driver=None) as pg:
        a = ArmazemPostgres(pg.get_connection_url())
        a.garantir_esquema()
        a.garantir_esquema()  # idempotente
        yield a


async def test_ciclo_completo_e_isolamento_por_repositorio(armazem: ArmazemPostgres) -> None:
    a, b = MemoriaDoRepositorio(armazem, "acme/a"), MemoriaDoRepositorio(armazem, "acme/b")
    await a.executar({"command": "create", "path": "/memories/c.md", "file_text": "usa pytest -q"})
    await a.executar({"command": "create", "path": "/memories/c.md", "file_text": "usa pytest -x"})
    assert await a.executar({"command": "view", "path": "/memories/c.md"}) == "usa pytest -x"
    assert await b.executar({"command": "view", "path": "/memories"}) == "(vazio)"
    assert await armazem.apagar("acme/a", "c.md") is True
    assert await armazem.apagar("acme/a", "c.md") is False
