import pytest
from hypothesis import given
from hypothesis import strategies as st

from forja.domain.politica import (
    Orcamento,
    Politica,
    PoliticaInvalida,
    Tier,
    casar_glob,
)

DOC = {
    "risk_tiers": {
        "high": {
            "paths": ["**/auth/**", "**/migrations/**", "infra/**", ".github/workflows/**"],
            "labels": ["security"],
        },
        "medium": {"paths": ["src/**"], "max_diff_lines": 400},
        "low": {"paths": ["docs/**", "**/*.md", "tests/**"]},
    },
    "budgets": {"per_intent_usd": 5.0, "max_sessions_per_intent": 20},
}
P = Politica.de_dict(DOC)


@pytest.mark.parametrize(
    ("padrao", "caminho", "esperado"),
    [
        ("docs/**", "docs/a/b.md", True),
        ("docs/**", "docs", False),
        ("**/*.md", "README.md", True),
        ("**/*.md", "a/b/c.md", True),
        ("**/*.md", "a/b/c.mdx", False),
        ("**/auth/**", "src/auth/x.py", True),
        ("**/auth/**", "auth/x.py", True),
        ("**/auth/**", "src/oauth/x.py", False),
        ("src/*.py", "src/a.py", True),
        ("src/*.py", "src/a/b.py", False),
        ("a?c", "abc", True),
        ("a.c", "abc", False),
        (".github/workflows/**", ".github/workflows/ci.yml", True),
    ],
)
def test_glob(padrao: str, caminho: str, esperado: bool) -> None:
    assert casar_glob(padrao, caminho) is esperado


def test_tier_final_e_o_maior_entre_caminhos_labels_e_tamanho() -> None:
    assert P.classificar(["docs/a.md", "tests/t.py"], [], 10).tier is Tier.BAIXO
    assert P.classificar(["docs/a.md", "src/x.py"], [], 10).tier is Tier.MEDIO
    assert P.classificar(["docs/a.md", "src/auth/x.py"], [], 10).tier is Tier.ALTO
    assert P.classificar(["docs/a.md"], ["Security"], 10).tier is Tier.ALTO
    assert P.classificar(["src/x.py"], [], 401).tier is Tier.ALTO  # passou do máximo do médio
    assert P.classificar(["src/x.py"], [], 400).tier is Tier.MEDIO
    c = P.classificar(["infra/k8s.yaml", ".github/workflows/ci.yml"], [], 1)
    assert c.tier is Tier.ALTO and len(c.motivos) == 2


def test_fail_closed_sem_politica_e_sem_caminhos_e_caminho_desconhecido() -> None:
    fechado = Politica.padrao_fechado()
    assert fechado.classificar(["docs/a.md"], [], 1).tier is Tier.ALTO
    assert P.classificar([], [], 0).tier is Tier.ALTO
    assert P.classificar(["scripts/deploy.sh"], [], 1).tier is Tier.MEDIO
    assert Tier.BAIXO.exige_humano is False and Tier.MEDIO.exige_humano


@given(
    st.lists(
        st.sampled_from(["docs/a.md", "src/x.py", "src/auth/y.py", "scripts/z.sh"]), min_size=1
    ),
    st.sampled_from(["infra/main.tf", "src/migrations/1.sql", ".github/workflows/ci.yml"]),
)
def test_acrescentar_arquivo_de_alto_risco_nunca_baixa_o_tier(
    caminhos: list[str], alto: str
) -> None:
    antes = P.classificar(caminhos, [], 10).tier
    depois = P.classificar([*caminhos, alto], [], 10).tier
    assert depois >= antes and depois is Tier.ALTO


def test_orcamento_por_intencao_e_por_sessoes() -> None:
    assert P.estourou_orcamento(4.99, 19) is None
    assert "orçamento" in (P.estourou_orcamento(5.0, 1) or "")
    assert "sessões" in (P.estourou_orcamento(0.1, 20) or "")
    assert Politica(orcamento=Orcamento(None, None, None)).estourou_orcamento(999, 999) is None


@pytest.mark.parametrize(
    "dados",
    [
        {"outra": 1},
        {"risk_tiers": {"critico": {}}},
        {"risk_tiers": {"high": {"paths": "infra/**"}}},
        {"risk_tiers": {"high": {"paths": [1]}}},
        {"risk_tiers": {"high": {"paths": ["x"], "extra": 1}}},
        {"risk_tiers": {"medium": {"max_diff_lines": -1}}},
        {"risk_tiers": {"medium": {"max_diff_lines": True}}},
        {"budgets": {"per_intent_usd": "5"}},
        {"budgets": {"per_intent_usd": 0}},
        {"risk_tiers": []},
    ],
)
def test_politica_invalida_e_recusada(dados: dict[str, object]) -> None:
    with pytest.raises(PoliticaInvalida):
        Politica.de_dict(dados)


def test_orcamento_padrao_quando_nao_declarado_e_vazio_e_valido() -> None:
    p = Politica.de_dict({})
    assert (
        p.declarada
        and p.orcamento == Orcamento()
        and p.classificar(["docs/a.md"], [], 1).tier is Tier.MEDIO
    )


def test_padrao_adversario_do_repositorio_nao_causa_backtracking_exponencial() -> None:
    import time

    caminho = "/".join(["a"] * 60) + "/b.txt"
    adversarios = [
        "/".join(["**"] * 40) + "/x",
        "**/" * 30 + "*.py",
        "*a" * 50 + "b",
        "/".join(["*a*a*a*a*a*b"] * 20),
        "**/" + "*/" * 30 + "x",
    ]
    inicio = time.monotonic()
    for padrao in adversarios:
        assert casar_glob(padrao, caminho) is False
    assert time.monotonic() - inicio < 1.0
    assert casar_glob("/".join(["**"] * 40) + "/b.txt", caminho) is True  # e os que casam, casam


def _glob_antigo(padrao: str, caminho: str) -> bool:
    """A semântica original (regex), usada só como oráculo em corpus pequeno."""
    import re

    saida: list[str] = []
    i = 0
    while i < len(padrao):
        if padrao.startswith("**/", i):
            saida.append("(?:.*/)?")
            i += 3
        elif padrao.startswith("**", i):
            saida.append(".*")
            i += 2
        elif padrao[i] == "*":
            saida.append("[^/]*")
            i += 1
        elif padrao[i] == "?":
            saida.append("[^/]")
            i += 1
        else:
            saida.append(re.escape(padrao[i]))
            i += 1
    return re.fullmatch("".join(saida), caminho) is not None


def test_glob_linear_preserva_a_semantica_antiga_num_corpus_exaustivo() -> None:
    import itertools

    pedacos = ["a", "b", "/", "*", "**", "?", "**/", "."]
    padroes = ["".join(p) for n in range(1, 4) for p in itertools.product(pedacos, repeat=n)]
    caminhos = ["".join(c) for n in range(0, 6) for c in itertools.product("ab/.", repeat=n)]
    for padrao in padroes:
        for caminho in caminhos:
            assert casar_glob(padrao, caminho) == _glob_antigo(padrao, caminho), (padrao, caminho)


@given(
    st.text(alphabet="ab/.*?", min_size=1, max_size=12),
    st.text(alphabet="ab/.", min_size=0, max_size=14),
)
def test_glob_linear_igual_ao_antigo_em_padroes_aleatorios(padrao: str, caminho: str) -> None:
    assert casar_glob(padrao, caminho) == _glob_antigo(padrao, caminho)


def test_regressao_deploy_dois_asteriscos_ponto_tf_casa_arquivo_em_subdiretorio() -> None:
    assert casar_glob("deploy/**.tf", "deploy/prod/main.tf") is True
    p = Politica.de_dict(
        {"risk_tiers": {"high": {"paths": ["deploy/**.tf"]}, "low": {"paths": ["deploy/**"]}}}
    )
    assert p.classificar(["deploy/prod/main.tf"], [], 1).tier is Tier.ALTO


def test_caminho_acima_do_teto_e_alto_nao_baixo() -> None:
    p = Politica.de_dict({"risk_tiers": {"low": {"paths": ["src/**"]}}})
    longo = "src/" + "a/" * 200 + "auth/login.py"
    assert len(longo) > 400
    c = p.classificar([longo], [], 1)
    assert c.tier is Tier.ALTO and "acima de 400" in " ".join(c.motivos)
    assert p.classificar(["src/a.py"], [], 1).tier is Tier.BAIXO


def test_forja_e_github_sao_sempre_alto_mesmo_com_politica_que_os_libera() -> None:
    p = Politica.de_dict({"risk_tiers": {"low": {"paths": ["**"]}}})
    for caminho in (".github/workflows/ci.yml", ".forja/policy.yaml", ".forja/bands.yaml",
                    ".forja/skills/x/SKILL.md", ".forja/outra-intent/spec.md"):  # fmt: skip
        assert p.classificar([caminho], [], 1, intent_id="0123456789abcdef").tier is Tier.ALTO, (
            caminho
        )
    # os artefatos da própria intenção não elevam
    assert (
        p.classificar([".forja/0123456789abcdef/spec.md"], [], 1, "0123456789abcdef").tier
        is Tier.BAIXO
    )
    assert p.classificar(["src/a.py", ".github/x.yml"], [], 1).tier is Tier.ALTO
