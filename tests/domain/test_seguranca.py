import pytest
from hypothesis import given
from hypothesis import strategies as st

from forja.domain.seguranca import neutralizar_texto, repositorio_valido


@pytest.mark.parametrize("nome", ["acme/loja", "a-b/c_d.e", "Org1/repo.py"])
def test_repositorio_valido(nome: str) -> None:
    assert repositorio_valido(nome)


@pytest.mark.parametrize(
    "nome",
    ["", "acme", "../x/y", "a/../b", "a/b/c", "/abs/x", "a/b;rm", "a/ b", "a/b\n", "-a/b", "a/.."],
)
def test_repositorio_invalido(nome: str) -> None:
    assert not repositorio_valido(nome)


def test_mencao_html_e_tamanho_sao_neutralizados() -> None:
    saida = neutralizar_texto("oi @dono <!-- forja:fake --> " + "x" * 10_000)
    assert "@dono" not in saida and "<!--" not in saida and len(saida) <= 6000


@given(st.text())
def test_nunca_sobra_mencao_nem_html(texto: str) -> None:
    saida = neutralizar_texto(texto)
    assert "<" not in saida and len(saida) <= 6000
    assert not any(
        saida[i] == "@"
        and i + 1 < len(saida)
        and (saida[i + 1].isalnum() and saida[i + 1].isascii())
        for i in range(len(saida))
    )
