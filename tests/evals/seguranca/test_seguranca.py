# pyright: basic
"""Regressão determinística de segurança (ADR 0047): código de produção, sem modelo.

Para cada caso: (1) com a proteção ligada o caso passa; (2) com o defeito original reintroduzido
por mutação o caso FALHA, provando que o eval enxerga a proteção. Não mede qualidade de agente.
"""

import pytest

from forja.domain.avaliacao import EXECUTOR_NENHUM, Relatorio, ResultadoDeTarefa
from tests.evals.seguranca.casos import CASOS

pytestmark = pytest.mark.eval_regressao


def test_cada_caso_diz_se_reproduz_falha_historica_ou_e_invariante() -> None:
    """`falhava_em`: SHAs contra cujo `git archive` o caso foi rodado e falhou (ADR 0047)."""
    historicos = {c.id for c in CASOS if c.falhava_em}
    invariantes = {c.id for c in CASOS if not c.falhava_em}
    assert len(historicos) == 14 and invariantes == {
        "m6-sem-dados",  # série vazia/NaN nunca foi o defeito real do M6
        "m4-hook-nega-por-padrao",  # os buracos do M4 foram corrigidos antes destes casos
        "m3-caminho-do-modelo",
        "m3-saida-nao-confiavel",
    }


def test_ha_casos_de_varias_origens_e_ids_unicos() -> None:
    ids = [c.id for c in CASOS]
    assert len(CASOS) == 18 and len(set(ids)) == len(ids)
    assert {i.split("-")[0] for i in ids} == {"m3", "m4", "m5", "m6"}
    assert all(c.origem.strip() for c in CASOS)


@pytest.mark.parametrize("caso", CASOS, ids=[c.id for c in CASOS])
async def test_com_a_protecao_ligada_o_caso_passa(caso) -> None:
    await caso.executar()


@pytest.mark.parametrize("caso", CASOS, ids=[c.id for c in CASOS])
async def test_com_a_protecao_desligada_o_caso_falha(caso, monkeypatch) -> None:
    caso.desligar(monkeypatch)
    with pytest.raises(AssertionError):  # falha do grader, não uma exceção qualquer
        await caso.executar()


def test_o_relatorio_diz_que_nao_ha_modelo_e_conta_todas_as_tarefas() -> None:
    tarefas = tuple(ResultadoDeTarefa(c.id, 1, 1) for c in CASOS)
    r = Relatorio("seguranca-deterministica", EXECUTOR_NENHUM, tarefas)
    assert not r.mede_qualidade_de_agente and r.pass_hat_k(1) == 1.0
    assert "sem modelo" in r.texto() and "HARNESS" in r.texto()
