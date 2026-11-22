import pytest

from forja.domain.artefatos import (
    ArtefatoInvalido,
    Cenario,
    Fonte,
    IntentMd,
    NomeDeArtefato,
    PassoDoPlano,
    Plano,
    Spec,
    caminho_do_artefato,
    caminho_relativo_seguro,
    linha_unica,
)

ID = "0123456789abcdef"


def test_caminho_do_artefato_so_aceita_id_e_nome_conhecidos() -> None:
    assert caminho_do_artefato(ID, NomeDeArtefato.SPEC) == f".forja/{ID}/spec.md"
    for ruim in ("../x", "abc", ID + "0", "0123456789ABCDEF", ""):
        with pytest.raises(ArtefatoInvalido):
            caminho_do_artefato(ruim, "spec.md")
    with pytest.raises(ArtefatoInvalido):
        caminho_do_artefato(ID, "../../etc/passwd")


@pytest.mark.parametrize("ok", ["src/app.py", "tests/a b/c.py", "README.md", ".github/ci.yml"])
def test_caminho_relativo_seguro_aceita(ok: str) -> None:
    assert caminho_relativo_seguro(ok) == ok


@pytest.mark.parametrize(
    "ruim",
    ["", "/etc/passwd", "~/x", "../x", "a/../b", "a//b", "a/./b", ".git/config", "a/.git/hooks/x",
     "a\\b", "a\nb", "a/", "x" * 301, "a/\x00b", "$(rm)/x", "a/`b`"],
)  # fmt: skip
def test_caminho_relativo_seguro_recusa(ruim: str) -> None:
    with pytest.raises(ArtefatoInvalido):
        caminho_relativo_seguro(ruim)


def test_plano_exige_passos_e_caminhos_seguros() -> None:
    with pytest.raises(ArtefatoInvalido):
        Plano(())
    with pytest.raises(ArtefatoInvalido):
        Plano((PassoDoPlano("../fora", "x", ()),))
    plano = Plano((PassoDoPlano("a.py", "x", ("t",)), PassoDoPlano("a.py", "y", ())))
    assert plano.arquivos == ("a.py",)


def test_texto_de_modelo_nao_abre_titulo_nem_bloco() -> None:
    assert "\n" not in linha_unica("a\n## injetado\n```")
    spec = Spec(
        requisitos=("ok\n# Título falso",),
        restricoes=(),
        cenarios=(Cenario("c\n```\nfim", ("Dado x\n## y",)),),
        adrs_afetados=(),
        pontos_em_aberto=("p",),
        fontes=(Fonte("i", "src/a.py", "c" * 40),),
    )
    md = spec.renderizar()
    titulos = [linha for linha in md.splitlines() if linha.startswith("#")]
    assert titulos == [
        "# spec", "## Requisitos", "## Restrições", "## Critérios de aceite",
        "## ADRs afetados", "## Pontos em aberto", "## Fontes",
    ]  # fmt: skip
    assert md.count("```") == 2 and "src/a.py@cccccccccccc" in md


def test_intent_md_traz_problema_origem_e_criterios() -> None:
    md = IntentMd("Login falha", ("passa o teste",), "github:a/b#1", "https://x/1").renderizar()
    assert "Login falha" in md and "- passa o teste" in md and "github:a/b#1" in md
