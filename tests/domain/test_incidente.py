from forja.domain.artefatos import Fonte
from forja.domain.bandas import Amostra, Banda
from forja.domain.incidente import Evidencia, Incidente


def test_evidencia_e_calculada_pelo_codigo_a_partir_da_serie() -> None:
    e = Evidencia.da_serie(
        Banda("lat", "q", 0.3, 600), [Amostra(1, 0.4), Amostra(2, 0.9), Amostra(3, 0.5)]
    )
    assert (e.atual, e.pico, e.amostras) == (0.5, 0.9, 3) and "banda lat" in e.resumo()


def test_incident_md_e_issue_nao_abrem_titulo_e_pedem_o_label_humano() -> None:
    e = Evidencia("lat", 0.3, 600, 0.5, 0.9, 3)
    inc = Incidente(
        e, "causa\n## injetada", "reverter\n# x", ("a\n# b",), (Fonte("i", "src/a.py", "c" * 40),)
    )
    md = inc.incident_md()
    titulos = [linha for linha in md.splitlines() if linha.startswith("#")]
    assert titulos == [
        "# incident",
        "## Banda violada",
        "## Evidências",
        "## Hipótese",
        "## Proposta",
        "## Fontes",
    ]
    assert "src/a.py@cccccccccccc" in md
    assert "forja:intent" in inc.corpo_da_issue() and "\n#" not in inc.corpo_da_issue()
