"""Índice Postgres real (pgvector) em contêiner; roda só no CI: `pytest -m integration`."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from testcontainers.community.postgres import PostgresContainer

from forja.application.casos_de_uso.indexar_repositorio import IndexarRepositorio
from forja.application.casos_de_uso.recuperar_conhecimento import RecuperarConhecimento
from forja.domain.knowledge import Escopo, Filtro
from forja.infrastructure.knowledge.chunker import ChunkerEstrutural
from forja.infrastructure.knowledge.contexto import ContextoPorEstrutura
from forja.infrastructure.knowledge.embedder_falso import EmbedderFalso
from forja.infrastructure.knowledge.postgres import IndicePostgres
from forja.infrastructure.knowledge.varredura import VarreduraDeDiretorio

pytestmark = pytest.mark.integration

A = Escopo("acme", "loja")
B = Escopo("acme", "banco")
EMB = EmbedderFalso(32)
CODIGO = "def validar_assinatura_webhook(corpo):\n    return corpo\n"


@pytest.fixture(scope="module")
def indice() -> Iterator[IndicePostgres]:
    with PostgresContainer("pgvector/pgvector:pg16", driver=None) as pg:
        idx = IndicePostgres(pg.get_connection_url())
        idx.garantir_esquema(EMB.dimensao)
        yield idx


def indexar(indice: IndicePostgres, raiz: Path, escopo: Escopo) -> None:
    IndexarRepositorio(
        VarreduraDeDiretorio(raiz, "c1"),
        ChunkerEstrutural(),
        EMB,
        ContextoPorEstrutura(),
        indice,
    ).executar(escopo)


def test_indexa_busca_e_isola_por_escopo(indice: IndicePostgres, tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(CODIGO)
    (tmp_path / "b.py").write_text("def enviar_email(dest):\n    return dest\n")
    indexar(indice, tmp_path, A)
    indexar(indice, tmp_path, B)
    indice.garantir_esquema(EMB.dimensao)  # idempotente

    caso = RecuperarConhecimento(indice, EMB)
    for escopo in (A, B):
        pagina = caso.buscar(escopo, "validar assinatura webhook")
        assert pagina.itens
        assert pagina.itens[0].trecho.simbolo == "validar_assinatura_webhook"
        assert all(r.trecho.escopo == escopo for r in pagina.itens)

    assert indice.buscar_lexical(Escopo("acme", "vazio"), "validar", 10, Filtro()) == []
    assert (
        indice.buscar_vetorial(Escopo("outra", "loja"), EMB.embutir(["validar"])[0], 10, Filtro())
        == []
    )


def test_incremental_e_remocao_no_postgres(indice: IndicePostgres, tmp_path: Path) -> None:
    escopo = Escopo("acme", "incremental")
    (tmp_path / "a.py").write_text(CODIGO)
    (tmp_path / "b.py").write_text("def x():\n    return 1\n")
    indexar(indice, tmp_path, escopo)
    antes = indice.versoes_por_arquivo(escopo)
    indexar(indice, tmp_path, escopo)
    assert indice.versoes_por_arquivo(escopo) == antes
    (tmp_path / "b.py").unlink()
    indexar(indice, tmp_path, escopo)
    assert set(indice.versoes_por_arquivo(escopo)) == {"a.py"}
    assert indice.obter_simbolo(escopo, "b.py", "x") == []
    (trecho,) = indice.obter_simbolo(escopo, "a.py", "validar_assinatura_webhook")
    assert trecho.commit == "c1"


def test_consulta_com_sintaxe_de_tsquery_nao_quebra(indice: IndicePostgres, tmp_path: Path) -> None:
    escopo = Escopo("acme", "tsquery")
    (tmp_path / "a.py").write_text(CODIGO)
    indexar(indice, tmp_path, escopo)
    caso = RecuperarConhecimento(indice, EMB)
    for consulta in ("validar & !(assinatura | ", "'; DROP TABLE knowledge_trecho; --", ":*"):
        caso.buscar(escopo, consulta)
    assert caso.buscar(escopo, "validar assinatura").itens
