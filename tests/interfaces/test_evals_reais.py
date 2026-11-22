# pyright: basic
import io

import pytest

from forja.interfaces.cli.evals_reais import OBRIGATORIAS, faltando, main

COMPLETO = {
    "FORJA_EVAL_MODELO_REAL": "true",
    "ANTHROPIC_API_KEY": "x",
    "FORJA_EVAL_MODELO": "m",
    "FORJA_EVAL_RUBRICA": "r",
    "FORJA_EVAL_LIMIAR": "0.8",
}


def test_pedida_sem_configuracao_falha_alto_e_diz_o_que_falta() -> None:
    saida = io.StringIO()
    assert main({}, saida) == 2
    for nome in OBRIGATORIAS:
        assert nome in saida.getvalue()


@pytest.mark.parametrize("remover", list(COMPLETO))
def test_qualquer_item_faltando_falha(remover: str) -> None:
    ambiente = {k: v for k, v in COMPLETO.items() if k != remover}
    assert main(ambiente, io.StringIO()) == 2 and remover in faltando(ambiente)


def test_opt_in_precisa_ser_true() -> None:
    assert main({**COMPLETO, "FORJA_EVAL_MODELO_REAL": "1"}, io.StringIO()) == 2


def test_com_tudo_configurado_ainda_falha_porque_a_camada_nao_existe() -> None:
    saida = io.StringIO()
    assert main(COMPLETO, saida) == 3 and "NÃO está implementada" in saida.getvalue()
    # nunca devolve 0: não existe caminho verde para a camada real
