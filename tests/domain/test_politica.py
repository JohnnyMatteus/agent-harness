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
