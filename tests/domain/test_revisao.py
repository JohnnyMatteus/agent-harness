import pytest

from forja.domain.politica import Classificacao, Tier
from forja.domain.revisao import (
    Achado,
    ArquivoDoDiff,
    DiffDaEntrega,
    ResultadoDaRevisao,
    Severidade,
    achado_validado,
    checar_testes,
    renderizar_review,
    tier_com_achados,
    varrer_segredos,
)


def diff(*arquivos: ArquivoDoDiff) -> DiffDaEntrega:
    return DiffDaEntrega(arquivos, "a" * 40)


def arq(caminho: str, patch: str = "", status: str = "modified") -> ArquivoDoDiff:
    return ArquivoDoDiff(caminho, status, 3, 1, patch)


def test_scanner_pega_segredo_em_linha_adicionada_e_arquivo_de_segredo() -> None:
    d = diff(
        arq("src/a.py", "+TOKEN = 'ghp_" + "a" * 30 + "'\n"),
        arq("src/b.py", "-antigo = 'ghp_" + "b" * 30 + "'\n"),  # removido não conta
        arq(".env", "+X=1"),
        arq("src/limpo.py", "+x = 1"),
        arq("config/server.pem", status="removed"),
    )
    achados = varrer_segredos(d)
    assert [(a.arquivo, a.severidade, a.risco) for a in achados] == [
        ("src/a.py", Severidade.BLOQUEANTE, Tier.ALTO),
        (".env", Severidade.BLOQUEANTE, Tier.ALTO),
    ]


def test_revisor_de_testes_pega_codigo_sem_teste() -> None:
    assert checar_testes(diff(arq("src/a.py")))[0].severidade is Severidade.AVISO
    assert checar_testes(diff(arq("src/a.py"), arq("tests/test_a.py"))) == ()
    assert checar_testes(diff(arq("README.md"))) == ()


def test_achado_so_aponta_para_arquivo_do_diff_e_linha_plausivel() -> None:
    d = diff(arq("src/a.py"))
    ok = achado_validado(d, "seguranca", Severidade.AVISO, "x\ny", "src/a.py", 10, Tier.MEDIO)
    assert ok.mensagem == "x y"
    for arquivo, linha in [
        ("src/inventado.py", None),
        ("src/a.py", 0),
        (None, 3),
        ("src/a.py", 10**9),
    ]:
        with pytest.raises(ValueError, match=r"fora do diff|linha"):
            achado_validado(d, "seguranca", Severidade.AVISO, "m", arquivo, linha, Tier.BAIXO)
    with pytest.raises(ValueError, match="desconhecido"):
        Achado("chefe", Severidade.AVISO, "m")


def test_tier_final_inclui_o_risco_dos_achados() -> None:
    base = Classificacao(Tier.BAIXO, ())
    achados = [Achado("seguranca", Severidade.AVISO, "m", None, None, Tier.ALTO)]
    c = tier_com_achados(base, achados)
    assert c.tier is Tier.ALTO and "achado" in c.motivos[-1]
    assert tier_com_achados(base, []).tier is Tier.BAIXO


def test_review_md_traz_risco_revisores_e_achados_sem_abrir_titulo() -> None:
    achados = (
        Achado("seguranca", Severidade.BLOQUEANTE, "ruim\n## Falso", "src/a.py", 4, Tier.ALTO),
    )
    r = ResultadoDaRevisao(achados, Classificacao(Tier.ALTO, ("infra/**",)))
    md = renderizar_review(r, {"seguranca": "uma linha\n# injetado"})
    titulos = [linha for linha in md.splitlines() if linha.startswith("#")]
    assert titulos == [
        "# review",
        "## Risco: alto",
        "## seguranca",
        "## testes",
        "## adrs",
        "## desempenho",
    ]
    assert "**bloqueante** `src/a.py:4`" in md and r.bloqueantes == achados


def test_diff_incompleto_eleva_o_tier_e_nunca_fica_baixo() -> None:
    from forja.domain.politica import Politica
    from forja.domain.revisao import TETO_DE_PATCH, elevar_por_diff_incompleto

    p = Politica.de_dict({"risk_tiers": {"low": {"paths": ["docs/**"]}}})

    def tier(d: DiffDaEntrega) -> Tier:
        return elevar_por_diff_incompleto(p.classificar(d.caminhos, [], 5), d).tier

    inteiro = diff(arq("docs/a.md", "+x"))
    assert tier(inteiro) is Tier.BAIXO
    # lista cortada pelo compare (ou no teto de 300): alto
    assert tier(DiffDaEntrega(inteiro.arquivos, "a" * 40, cortado=True)) is Tier.ALTO
    assert tier(diff(*(arq(f"docs/{i}.md", "+x") for i in range(300)))) is Tier.ALTO
    # o revisor não viu tudo: no mínimo médio
    assert tier(diff(arq("docs/a.md", "+" + "x" * TETO_DE_PATCH))) is Tier.MEDIO
    assert tier(diff(arq("docs/a.md", ""))) is Tier.MEDIO  # linhas alteradas e sem patch
    assert tier(diff(*(arq(f"docs/{i}.md", "+" + "x" * 5000) for i in range(20)))) is Tier.MEDIO


def test_rename_conta_o_caminho_de_origem() -> None:
    d = diff(ArquivoDoDiff("docs/main.tf", "renamed", 0, 0, "", "infra/main.tf"))
    assert d.caminhos == ("docs/main.tf", "infra/main.tf")


def test_avanco_aceito_e_so_o_commit_do_review() -> None:
    from forja.domain.revisao import AvancoDaBranch

    r = ".forja/x/review.md"
    assert AvancoDaBranch(1, (r,)).so_o_review(r) and AvancoDaBranch(0, ()).so_o_review(r)
    assert not AvancoDaBranch(1, (r, "src/a.py")).so_o_review(r)
    assert not AvancoDaBranch(2, (r,)).so_o_review(r)
    assert not AvancoDaBranch(1, ("src/a.py",)).so_o_review(r)
