import pytest

from forja.infrastructure.yaml_estrito import YamlInvalido, ler

POLITICA = """
# política do repositório
risk_tiers:
  high:      # sempre humano
    paths: ["**/auth/**", "infra/**", ".github/workflows/**"]
    labels: ["security"]
  medium:
    paths: ["src/**"]
    max_diff_lines: 400
  low:
    paths: ["docs/**", "**/*.md", "tests/**"]
budgets:
  per_intent_usd: 5.00
  max_sessions_per_intent: 20
"""

BANDAS = """
service: payments-events-go
bands:
  - id: webhook-latency-p95
    query: histogram_quantile(0.95, sum(rate(http_duration_bucket{route="/webhook"}[5m])) by (le))
    max: 0.300
    for: 10m
    on_breach: diagnose_and_write_intent
  - id: dlq-rate
    query: sum(rate(dlq_messages_total[15m]))
    max: 0.1
"""


def test_le_a_politica_do_design_doc() -> None:
    dados = ler(POLITICA)
    assert dados["risk_tiers"]["high"]["paths"] == [
        "**/auth/**",
        "infra/**",
        ".github/workflows/**",
    ]
    assert dados["risk_tiers"]["medium"]["max_diff_lines"] == 400
    assert dados["budgets"] == {"per_intent_usd": 5.0, "max_sessions_per_intent": 20}


def test_le_lista_de_mapeamentos_com_consulta_promql() -> None:
    dados = ler(BANDAS)
    assert dados["service"] == "payments-events-go" and len(dados["bands"]) == 2
    assert dados["bands"][0]["query"].startswith("histogram_quantile(0.95,")
    assert dados["bands"][0]["max"] == 0.3 and dados["bands"][0]["for"] == "10m"
    assert dados["bands"][1]["id"] == "dlq-rate"


@pytest.mark.parametrize(
    "texto",
    [
        "a: &ancora 1",
        "a: *ancora",
        "a: !!python/object x",
        "a: |\n  bloco",
        "a: >\n  bloco",
        "a: {b: 1}",
        "---\na: 1",
        "a:\n\tb: 1",
        "a: 1\na: 2",
        "a: [1, [2]]",
        "a: [1,",
        "a: 'sem fechar",
        "- ",
        "nao e mapa",
        "a:\n  b: 1\n c: 2",
        "x" * 70_000,
    ],
)
def test_recusa_o_que_esta_fora_do_subconjunto(texto: str) -> None:
    with pytest.raises(YamlInvalido):
        ler(texto)


def test_vazio_e_comentario_e_aninhamento_excessivo() -> None:
    assert ler("") == {} and ler("# só comentário\n") == {}
    fundo = "".join("  " * i + f"k{i}:\n" for i in range(12)) + "  " * 12 + "v: 1"
    with pytest.raises(YamlInvalido, match="aninhamento"):
        ler(fundo)


def test_hash_dentro_de_aspas_nao_e_comentario() -> None:
    assert ler('a: "x # y"\nb: z # c') == {"a": "x # y", "b": "z"}
