import pytest

from forja.domain.entrega import Entrega
from forja.domain.erros import CiclosEsgotados, IntentInvalida, TransicaoInvalida
from forja.domain.estados import Estado, RaioDeImpacto
from forja.domain.eventos import EntregaConcluida, PlanoPronto, PRAberto, SpecPronta


def entrega(maximo: int = 3) -> Entrega:
    return Entrega(intent_id="abc", ciclos_maximos=maximo)


def ate_test(e: Entrega) -> Entrega:
    e.confirmar_intent()
    e.concluir_spec(pontos_em_aberto=0)
    e.concluir_build()
    return e


def test_caminho_feliz_raio_baixo_emite_eventos_nos_pontos_certos() -> None:
    e = entrega()
    e.confirmar_intent()
    e.concluir_spec(pontos_em_aberto=0)
    assert e.retirar_eventos() == [SpecPronta("abc")]
    e.concluir_build()
    assert e.retirar_eventos() == [PlanoPronto("abc")]
    e.registrar_verificacao(verde=True)
    assert e.retirar_eventos() == [PRAberto("abc")]
    e.concluir_review(achados_bloqueantes=False, raio=RaioDeImpacto.BAIXO)
    assert e.estado is Estado.DEPLOY
    e.concluir_deploy()
    assert e.estado is Estado.MAINTAIN
    assert e.retirar_eventos() == [EntregaConcluida("abc")]


def test_pontos_em_aberto_seguram_a_entrega_ate_humano_resolver() -> None:
    e = entrega()
    e.confirmar_intent()
    e.concluir_spec(pontos_em_aberto=2)
    assert e.estado is Estado.AGUARDANDO_SPEC
    assert e.retirar_eventos() == []
    with pytest.raises(TransicaoInvalida):
        e.concluir_build()
    e.resolver_pontos_em_aberto()
    assert e.estado is Estado.BUILD
    assert e.retirar_eventos() == [SpecPronta("abc")]


def test_falha_em_test_volta_ao_build_e_conta_ciclo() -> None:
    e = ate_test(entrega())
    e.registrar_verificacao(verde=False)
    assert (e.estado, e.ciclos_usados) == (Estado.BUILD, 1)


def test_ao_passar_de_n_ciclos_a_transicao_e_recusada_sem_mudar_estado() -> None:
    e = ate_test(entrega(maximo=2))
    for _ in range(2):
        e.registrar_verificacao(verde=False)
        e.concluir_build()
    with pytest.raises(CiclosEsgotados):
        e.registrar_verificacao(verde=False)
    assert (e.estado, e.ciclos_usados) == (Estado.TEST, 2)
    e.registrar_verificacao(verde=True)
    assert e.estado is Estado.REVIEW


def test_plano_e_pr_so_emitem_uma_vez_mesmo_com_ciclos() -> None:
    e = ate_test(entrega())
    e.registrar_verificacao(verde=False)
    e.concluir_build()
    e.registrar_verificacao(verde=True)
    e.concluir_review(achados_bloqueantes=True, raio=RaioDeImpacto.BAIXO)
    e.concluir_build()
    e.registrar_verificacao(verde=True)
    tipos = [type(ev) for ev in e.retirar_eventos()]
    assert tipos.count(PlanoPronto) == 1
    assert tipos.count(PRAberto) == 1


def test_raio_alto_exige_aprovacao_humana() -> None:
    e = ate_test(entrega())
    e.registrar_verificacao(verde=True)
    e.concluir_review(achados_bloqueantes=False, raio=RaioDeImpacto.ALTO)
    assert e.estado is Estado.AGUARDANDO_HUMANO
    with pytest.raises(TransicaoInvalida):
        e.concluir_deploy()
    e.aprovar("maria")
    assert (e.estado, e.aprovado_por) == (Estado.DEPLOY, "maria")


def test_politica_que_nega_deploy_tambem_chama_humano() -> None:
    e = ate_test(entrega())
    e.registrar_verificacao(verde=True)
    e.concluir_review(
        achados_bloqueantes=False, raio=RaioDeImpacto.BAIXO, politica_permite_deploy=False
    )
    assert e.estado is Estado.AGUARDANDO_HUMANO


def test_achados_bloqueantes_voltam_ao_build_mesmo_com_raio_alto() -> None:
    e = ate_test(entrega())
    e.registrar_verificacao(verde=True)
    e.concluir_review(achados_bloqueantes=True, raio=RaioDeImpacto.ALTO)
    assert e.estado is Estado.BUILD


def test_aprovacao_exige_aprovador_identificado() -> None:
    e = ate_test(entrega())
    e.registrar_verificacao(verde=True)
    e.concluir_review(achados_bloqueantes=False, raio=RaioDeImpacto.ALTO)
    with pytest.raises(IntentInvalida):
        e.aprovar(" ")
    assert e.estado is Estado.AGUARDANDO_HUMANO


def test_banda_violada_gera_proxima_entrega_em_plan() -> None:
    e = ate_test(entrega())
    e.registrar_verificacao(verde=True)
    e.concluir_review(achados_bloqueantes=False, raio=RaioDeImpacto.BAIXO)
    e.concluir_deploy()
    e.retirar_eventos()
    proxima = e.registrar_banda_violada("p95", "p95 > 800ms por 10 min", "novo")
    assert (proxima.estado, proxima.intent_id, proxima.ciclos_usados) == (Estado.PLAN, "novo", 0)
    assert e.estado is Estado.MAINTAIN


def test_banda_violada_fora_de_maintain_e_recusada() -> None:
    with pytest.raises(TransicaoInvalida):
        entrega().registrar_banda_violada("p95", "x", "novo")


def test_plan_nao_vai_direto_para_deploy() -> None:
    e = entrega()
    for comando in (
        e.concluir_deploy,
        e.concluir_build,
        e.resolver_pontos_em_aberto,
        lambda: e.aprovar("maria"),
        lambda: e.registrar_verificacao(verde=True),
        lambda: e.concluir_review(achados_bloqueantes=False, raio=RaioDeImpacto.BAIXO),
    ):
        with pytest.raises(TransicaoInvalida):
            comando()
    assert e.estado is Estado.PLAN
    assert e.retirar_eventos() == []


@pytest.mark.parametrize("maximo", [0, -1])
def test_limite_de_ciclos_invalido(maximo: int) -> None:
    with pytest.raises(IntentInvalida):
        entrega(maximo)
