import pytest

from forja.domain.knowledge import Escopo
from forja.infrastructure.knowledge.configuracao import (
    ConfiguracaoInvalida,
    embedder_do_ambiente,
)
from forja.infrastructure.knowledge.memoria import IndiceEmMemoria
from forja.infrastructure.knowledge.token_sessao import emitir_token
from forja.interfaces.mcp.composicao import servidor_do_ambiente

SEGREDO = "k" * 40


def ambiente(**extra: str) -> dict[str, str]:
    base = {
        "FORJA_KNOWLEDGE_TOKEN": emitir_token(Escopo("a", "b"), "s", SEGREDO),
        "FORJA_KNOWLEDGE_TOKEN_SECRET": SEGREDO,
        "FORJA_EMBEDDER": "falso",
    }
    return {**base, **extra}


async def test_compoe_o_servidor_com_o_escopo_do_token() -> None:
    servidor = servidor_do_ambiente(ambiente(), IndiceEmMemoria())
    assert {f.name for f in await servidor.list_tools()} == {
        "search_code",
        "search_docs",
        "get_symbol",
    }


@pytest.mark.parametrize(
    "extra",
    [
        {"FORJA_KNOWLEDGE_TOKEN": "adulterado"},
        {"FORJA_KNOWLEDGE_TOKEN": ""},
        {"FORJA_KNOWLEDGE_TOKEN_SECRET": "curto"},
        {"FORJA_EMBEDDER": "voyage"},
        {"FORJA_EMBEDDER": ""},
    ],
)
def test_configuracao_ruim_falha_em_vez_de_improvisar(extra: dict[str, str]) -> None:
    with pytest.raises(ConfiguracaoInvalida):
        servidor_do_ambiente(ambiente(**extra), IndiceEmMemoria())


def test_embedder_real_nao_e_simulado() -> None:
    with pytest.raises(ConfiguracaoInvalida, match="nao ha adaptador"):
        embedder_do_ambiente({"FORJA_EMBEDDER": "openai"})
