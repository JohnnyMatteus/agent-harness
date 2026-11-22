from hypothesis import given
from hypothesis import strategies as st

from forja.application.casos_de_uso.recuperar_conhecimento import RecuperarConhecimento
from forja.domain.knowledge import (
    Escopo,
    Filtro,
    TipoDeTrecho,
    Trecho,
    fundir_rrf,
    id_do_trecho,
)
from forja.infrastructure.knowledge.embedder_falso import EmbedderFalso
from forja.infrastructure.knowledge.memoria import IndiceEmMemoria

A = Escopo("acme", "loja")
B = Escopo("acme", "banco")
C = Escopo("outra", "loja")
EMB = EmbedderFalso(32)


def trecho(escopo: Escopo, caminho: str, simbolo: str, conteudo: str, **kw: object) -> Trecho:
    return Trecho(
        id=id_do_trecho(escopo, caminho, 0, conteudo),
        escopo=escopo,
        caminho=caminho,
        linguagem="python",
        tipo=kw.get("tipo", TipoDeTrecho.CODIGO),  # type: ignore[arg-type]
        simbolo=simbolo,
        linha_inicio=1,
        linha_fim=2,
        conteudo=conteudo,
        contexto="",
        commit="c1",
    )


def indexar(indice: IndiceEmMemoria, *trechos: Trecho) -> None:
    for t in trechos:
        indice.substituir_arquivo(
            t.escopo, t.caminho, "v", [(t, EMB.embutir([t.texto_indexado])[0])]
        )


def test_mesma_consulta_nao_vaza_entre_repositorios_nem_organizacoes() -> None:
    indice = IndiceEmMemoria()
    segredo = "def validar_assinatura_webhook(corpo): return hmac"
    indexar(
        indice,
        trecho(A, "a.py", "validar_assinatura_webhook", segredo),
        trecho(B, "b.py", "validar_assinatura_webhook", segredo),
        trecho(C, "c.py", "validar_assinatura_webhook", segredo),
    )
    caso = RecuperarConhecimento(indice, EMB)
    for escopo, caminho in ((A, "a.py"), (B, "b.py"), (C, "c.py")):
        pagina = caso.buscar(escopo, "validar assinatura webhook")
        assert [r.trecho.caminho for r in pagina.itens] == [caminho]
        assert all(r.trecho.escopo == escopo for r in pagina.itens)


def test_repositorio_sem_indice_devolve_vazio_mesmo_com_dados_nos_vizinhos() -> None:
    indice = IndiceEmMemoria()
    indexar(indice, trecho(A, "a.py", "f", "def f(): token"))
    assert RecuperarConhecimento(indice, EMB).buscar(B, "token f").itens == ()


def test_indice_defeituoso_nao_atravessa_o_escopo() -> None:
    class Defeituoso(IndiceEmMemoria):
        def buscar_lexical(self, escopo: Escopo, consulta: str, limite: int, filtro: Filtro):  # type: ignore[override]
            return super().buscar_lexical(A, consulta, limite, filtro)

    indice = Defeituoso()
    indexar(indice, trecho(A, "a.py", "f", "def f(): token"))
    assert RecuperarConhecimento(indice, EMB).buscar(B, "token f").itens == ()


def test_fusao_combina_nome_exato_e_parafrase() -> None:
    indice = IndiceEmMemoria()
    indexar(
        indice,
        trecho(A, "a.py", "calcular_frete", "def calcular_frete(peso): return peso * 2"),
        trecho(A, "b.py", "enviar_email", "def enviar_email(dest): smtp"),
        trecho(A, "c.py", "frete_gratis", "def frete_gratis(total): return total > 100"),
    )
    pagina = RecuperarConhecimento(indice, EMB).buscar(A, "calcular_frete")
    assert pagina.itens[0].trecho.simbolo == "calcular_frete"


def test_filtros_de_tipo_e_linguagem_entram_na_consulta() -> None:
    indice = IndiceEmMemoria()
    indexar(
        indice,
        trecho(A, "a.py", "f", "frete regra", tipo=TipoDeTrecho.CODIGO),
        trecho(A, "docs/adr/1.md", "Frete", "frete regra", tipo=TipoDeTrecho.ADR),
    )
    caso = RecuperarConhecimento(indice, EMB)
    so_adr = caso.buscar(A, "frete", filtro=Filtro(tipos=frozenset({TipoDeTrecho.ADR})))
    assert [r.trecho.caminho for r in so_adr.itens] == ["docs/adr/1.md"]


def test_paginacao_explicita() -> None:
    indice = IndiceEmMemoria()
    indexar(indice, *[trecho(A, f"f{i}.py", f"s{i}", f"frete numero {i}") for i in range(5)])
    caso = RecuperarConhecimento(indice, EMB)
    p1 = caso.buscar(A, "frete", limite=2)
    p2 = caso.buscar(A, "frete", limite=2, deslocamento=2)
    p3 = caso.buscar(A, "frete", limite=2, deslocamento=4)
    assert (p1.ha_mais, p2.ha_mais, p3.ha_mais) == (True, True, False)
    ids = [r.trecho.id for p in (p1, p2, p3) for r in p.itens]
    assert len(ids) == len(set(ids)) == 5


def test_consulta_vazia_nao_busca() -> None:
    assert RecuperarConhecimento(IndiceEmMemoria(), EMB).buscar(A, "  ").itens == ()


def test_rrf_exemplo() -> None:
    assert [i for i, _ in fundir_rrf([["a", "b"], ["b", "c"]])] == ["b", "a", "c"]


@given(st.lists(st.lists(st.sampled_from("abcdef"), unique=True), max_size=4))
def test_rrf_propriedades(listas: list[list[str]]) -> None:
    fundido = fundir_rrf(listas)
    ids = [i for i, _ in fundido]
    assert len(ids) == len(set(ids)) == len({i for lista in listas for i in lista})
    pontos = [p for _, p in fundido]
    assert pontos == sorted(pontos, reverse=True)
    assert fundir_rrf(listas) == fundido
