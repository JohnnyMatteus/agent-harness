# pyright: reportPrivateUsage=false
"""Propriedades da máquina de estados: qualquer sequência de comandos, válida ou não."""

from collections.abc import Callable
from contextlib import suppress

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from forja.domain.entrega import Entrega
from forja.domain.erros import ErroDeDominio, TransicaoInvalida
from forja.domain.estados import TRANSICOES, Estado, RaioDeImpacto

Comando = Callable[[Entrega], object]


def _spec(pontos: int) -> Comando:
    return lambda e: e.concluir_spec(pontos)


def _verificacao(verde: bool) -> Comando:
    return lambda e: e.registrar_verificacao(verde=verde)


def _review(bloqueantes: bool, raio: RaioDeImpacto, permite: bool) -> Comando:
    return lambda e: e.concluir_review(
        achados_bloqueantes=bloqueantes, raio=raio, politica_permite_deploy=permite
    )


def _aprovar(e: Entrega) -> None:
    e.aprovar("maria")


def _banda(e: Entrega) -> None:
    e.registrar_banda_violada("p95", "evidência", "novo")


comandos: st.SearchStrategy[Comando] = st.one_of(
    st.just(Entrega.confirmar_intent),
    st.integers(0, 2).map(_spec),
    st.just(Entrega.resolver_pontos_em_aberto),
    st.just(Entrega.concluir_build),
    st.booleans().map(_verificacao),
    st.builds(_review, st.booleans(), st.sampled_from(RaioDeImpacto), st.booleans()),
    st.just(_aprovar),
    st.just(Entrega.concluir_deploy),
    st.just(_banda),
)


@given(st.lists(comandos, max_size=40), st.integers(1, 5))
def test_deploy_so_depois_de_passar_por_review(sequencia: list[Comando], maximo: int) -> None:
    e = Entrega(intent_id="abc", ciclos_maximos=maximo)
    visitados = {e.estado}
    for comando in sequencia:
        with suppress(ErroDeDominio):
            comando(e)
        visitados.add(e.estado)
    if Estado.DEPLOY in visitados:
        assert Estado.REVIEW in visitados
    if Estado.MAINTAIN in visitados:
        assert Estado.DEPLOY in visitados


@given(st.lists(comandos, max_size=40), st.integers(1, 5))
def test_toda_mudanca_de_estado_e_aresta_do_grafo_e_recusa_nao_muda_nada(
    sequencia: list[Comando], maximo: int
) -> None:
    e = Entrega(intent_id="abc", ciclos_maximos=maximo)
    for comando in sequencia:
        antes = (e.estado, e.ciclos_usados, e.aprovado_por, len(e._eventos))
        try:
            comando(e)
        except ErroDeDominio:
            assert (e.estado, e.ciclos_usados, e.aprovado_por, len(e._eventos)) == antes
            continue
        if e.estado is not antes[0]:
            assert e.estado in TRANSICOES[antes[0]]
        assert e.ciclos_usados <= maximo


@given(st.sampled_from(Estado), st.sampled_from(Estado))
def test_destino_fora_do_grafo_e_recusado(origem: Estado, destino: Estado) -> None:
    e = Entrega(intent_id="abc", estado=origem)
    if destino in TRANSICOES[origem]:
        e._mover(destino)
        assert e.estado is destino
    else:
        try:
            e._mover(destino)
        except TransicaoInvalida:
            assert e.estado is origem
        else:
            raise AssertionError("transição fora do grafo foi aceita")


class MaquinaDeEntrega(RuleBasedStateMachine):
    """Explora sequências e confere invariantes após cada passo."""

    def __init__(self) -> None:
        super().__init__()
        self.entrega = Entrega(intent_id="abc", ciclos_maximos=2)
        self.passou_por_review = False

    @rule(comando=comandos)
    def aplicar(self, comando: Comando) -> None:
        with suppress(ErroDeDominio):
            comando(self.entrega)
        self.passou_por_review |= self.entrega.estado is Estado.REVIEW

    @invariant()
    def deploy_exige_review(self) -> None:
        if self.entrega.estado in (Estado.DEPLOY, Estado.MAINTAIN):
            assert self.passou_por_review

    @invariant()
    def ciclos_dentro_do_limite(self) -> None:
        assert 0 <= self.entrega.ciclos_usados <= 2


TestMaquinaDeEntrega = MaquinaDeEntrega.TestCase
TestMaquinaDeEntrega.settings = settings(max_examples=60, stateful_step_count=30, deadline=None)
