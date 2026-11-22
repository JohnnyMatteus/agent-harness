import pytest
from hypothesis import given
from hypothesis import strategies as st

from forja.domain.harness import (
    LIMIARES_PROVISORIOS,
    ContratoDeSprint,
    Criterio,
    Feature,
    FeatureList,
    FeatureListAdulterada,
    HarnessInvalido,
    comando_de_teste_valido,
    decidir_bloco,
    exigir_so_passes_mudou,
    features_que_passam,
)

TESTE = ("python", "-m", "pytest", "tests/test_a.py")


def f(id_: str, passes: bool = False) -> Feature:
    return Feature(id_, "funcional", f"faz {id_}", ("abre", "confere"), TESTE, passes)


def lista(*ids: str) -> FeatureList:
    return FeatureList(tuple(f(i) for i in ids))


@pytest.mark.parametrize(
    "argv",
    [
        (),
        ("rm", "-rf", "/"),
        ("python", "-c", "x"),
        ("python", "-m", "http.server"),
        ("pytest", "$(x)"),
        ("pytest", "a;b"),
        ("sh", "init.sh"),
        ("pytest", *("x",) * 25),
    ],
)
def test_comando_de_teste_recusa_o_que_nao_e_teste(argv: tuple[str, ...]) -> None:
    with pytest.raises(HarnessInvalido):
        comando_de_teste_valido(argv)


@pytest.mark.parametrize(
    "argv", [TESTE, ("pytest", "-q", "tests/a.py::t"), ("npm", "test"), ("go", "test", "./...")]
)
def test_comando_de_teste_aceita(argv: tuple[str, ...]) -> None:
    assert comando_de_teste_valido(argv) == argv


def test_json_vai_e_volta_e_recusa_passes_nao_booleano() -> None:
    original = lista("a", "b")
    assert FeatureList.de_json(original.para_json()) == original
    ruim = original.para_json().replace('"passes": false', '"passes": "sim"', 1)
    with pytest.raises(HarnessInvalido):
        FeatureList.de_json(ruim)
    with pytest.raises(HarnessInvalido):
        FeatureList.de_json("{")


def test_so_passes_pode_mudar() -> None:
    antes = lista("a", "b")
    exigir_so_passes_mudou(antes, antes.com_passes(frozenset({"a"})))
    adulterada = FeatureList((f("a"), Feature("b", "x", "outra descrição", ("p",), TESTE)))
    with pytest.raises(FeatureListAdulterada):
        exigir_so_passes_mudou(antes, adulterada)
    with pytest.raises(FeatureListAdulterada):
        exigir_so_passes_mudou(antes, lista("a"))
    with pytest.raises(FeatureListAdulterada):
        exigir_so_passes_mudou(antes.com_passes(frozenset({"a"})), antes)


@given(st.sets(st.sampled_from(["a", "b", "c", "d"])))
def test_com_passes_so_liga_o_que_foi_pedido_e_nunca_desliga(ids: set[str]) -> None:
    antes = lista("a", "b", "c", "d").com_passes(frozenset({"a"}))
    depois = antes.com_passes(frozenset(ids))
    exigir_so_passes_mudou(antes, depois)
    assert {x.id for x in depois.features if x.passes} == ids | {"a"}


def test_bloco_pega_os_pendentes_em_ordem() -> None:
    base = lista("a", "b", "c").com_passes(frozenset({"a"}))
    assert [x.id for x in base.bloco(5)] == ["b", "c"] and [x.id for x in base.bloco(1)] == ["b"]
    assert base.com_passes(frozenset({"b", "c"})).completa


def contrato(*features: str, limiar: int = 7) -> ContratoDeSprint:
    return ContratoDeSprint(1, features, ("e",), ("v",), {c: limiar for c in Criterio})


def test_contrato_so_cobre_pendentes_dentro_do_bloco() -> None:
    base = lista("a", "b").com_passes(frozenset({"a"}))
    contrato("b").exigir_dentro_de(base, 1)
    for ruim in (contrato("a"), contrato("zzz"), contrato("b", "b")):
        with pytest.raises(HarnessInvalido):
            ruim.exigir_dentro_de(base, 1)
    with pytest.raises(HarnessInvalido):
        ContratoDeSprint(1, ("b",), ("e",), ("v",), {Criterio.FUNCIONALIDADE: 7})


@given(st.dictionaries(st.sampled_from(list(Criterio)), st.integers(-3, 14)))
def test_limiar_rigido_abaixo_em_qualquer_criterio_reprova(notas: dict[Criterio, int]) -> None:
    v = decidir_bloco(LIMIARES_PROVISORIOS, notas)
    esperado = all(c in notas and 7 <= notas[c] <= 10 for c in Criterio)
    assert v.aprovado is esperado


def test_passes_exige_aprovacao_do_avaliador_e_teste_verde_da_propria_feature() -> None:
    c = contrato("a", "b")
    ok = decidir_bloco(c.limiares, dict.fromkeys(Criterio, 9))
    ruim = decidir_bloco(
        c.limiares, {**dict.fromkeys(Criterio, 9), Criterio.QUALIDADE_DE_CODIGO: 6}
    )
    assert features_que_passam(ok, {"a": True, "b": False}, c) == {"a"}
    assert features_que_passam(ok, {"a": True}, c) == {"a"}  # sem resultado não passa
    assert features_que_passam(ruim, {"a": True, "b": True}, c) == frozenset()
