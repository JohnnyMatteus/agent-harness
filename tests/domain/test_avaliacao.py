import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from forja.domain.avaliacao import (
    AVISO_EXECUTOR_FALSO,
    EXECUTOR_FALSO,
    AvaliacaoInvalida,
    Relatorio,
    ResultadoDeTarefa,
    pass_at_k,
    pass_hat_k,
)


def test_valores_conhecidos() -> None:
    assert pass_at_k(10, 0, 1) == 0 and pass_at_k(10, 10, 5) == 1
    assert pass_at_k(10, 5, 1) == pytest.approx(0.5) and pass_hat_k(10, 5, 1) == pytest.approx(0.5)
    # 2 de 4: pelo menos uma em 2 sorteadas = 1 - C(2,2)/C(4,2) = 5/6; as duas = C(2,2)/C(4,2) = 1/6
    assert pass_at_k(4, 2, 2) == pytest.approx(5 / 6)
    assert pass_hat_k(4, 2, 2) == pytest.approx(1 / 6)
    assert pass_at_k(5, 4, 2) == 1.0 and pass_hat_k(5, 1, 2) == 0.0  # n - c < k, c < k


@pytest.mark.parametrize(("n", "c", "k"), [(0, 0, 1), (3, 4, 1), (3, -1, 1), (3, 1, 0), (3, 1, 4)])
def test_contagens_impossiveis_sao_recusadas(n: int, c: int, k: int) -> None:
    with pytest.raises(AvaliacaoInvalida):
        pass_at_k(n, c, k)
    with pytest.raises(AvaliacaoInvalida):
        pass_hat_k(n, c, k)


@given(
    st.integers(1, 30).flatmap(
        lambda n: st.tuples(st.just(n), st.integers(0, n), st.integers(1, n))
    )
)
def test_propriedades(args: tuple[int, int, int]) -> None:
    n, c, k = args
    a, h = pass_at_k(n, c, k), pass_hat_k(n, c, k)
    assert 0 <= h <= a + 1e-12 and a <= 1 + 1e-12  # todas implica pelo menos uma
    if k == 1:
        assert math.isclose(a, c / n) and math.isclose(h, c / n)
    if c == n:
        assert a == 1 and h == 1
    if c == 0:
        assert a == 0 and h == 0
    if k < n:  # mais tentativas exigidas: pass@k sobe e pass^k desce
        assert pass_at_k(n, c, k + 1) >= a - 1e-12 and pass_hat_k(n, c, k + 1) <= h + 1e-12


def test_relatorio_exige_executor_e_tarefas_e_avisa_quando_o_executor_e_falso() -> None:
    t = (ResultadoDeTarefa("a", 4, 4), ResultadoDeTarefa("b", 4, 2))
    with pytest.raises(AvaliacaoInvalida, match="executor"):
        Relatorio("s", " ", t)
    with pytest.raises(AvaliacaoInvalida, match="nenhuma tarefa"):
        Relatorio("s", EXECUTOR_FALSO, ())
    falso = Relatorio("s", EXECUTOR_FALSO, t)
    assert not falso.mede_qualidade_de_agente and AVISO_EXECUTOR_FALSO in falso.texto(2)
    assert "executor: falso" in falso.texto() and falso.taxa() == 0.75
    real = Relatorio("s", "real:modelo-x", t)
    assert real.mede_qualidade_de_agente and AVISO_EXECUTOR_FALSO not in real.texto()
