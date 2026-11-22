import pytest

from forja.application.configuracao import VARIAVEL_CICLOS, Configuracao


def test_padrao_e_tres_ciclos() -> None:
    assert Configuracao.do_ambiente({}).max_ciclos_build_test == 3


def test_le_do_ambiente() -> None:
    assert Configuracao.do_ambiente({VARIAVEL_CICLOS: "5"}).max_ciclos_build_test == 5


@pytest.mark.parametrize("valor", ["0", "-1", "tres"])
def test_valor_invalido_falha(valor: str) -> None:
    with pytest.raises(ValueError, match=VARIAVEL_CICLOS):
        Configuracao.do_ambiente({VARIAVEL_CICLOS: valor})
