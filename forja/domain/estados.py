"""Estados e grafo de transições da Entrega (design doc, seção 5.1; ADR 0001)."""

from enum import StrEnum


class Estado(StrEnum):
    PLAN = "plan"
    DESIGN = "design"
    AGUARDANDO_SPEC = "aguardando_spec"
    BUILD = "build"
    TEST = "test"
    REVIEW = "review"
    AGUARDANDO_HUMANO = "aguardando_humano"
    DEPLOY = "deploy"
    MAINTAIN = "maintain"


class RaioDeImpacto(StrEnum):
    """No M1 entra como parâmetro; a classificação vem da política de risco (M5)."""

    BAIXO = "baixo"
    ALTO = "alto"


# Única fonte de verdade das arestas permitidas. Maintain -> Plan não é aresta desta
# Entrega: uma banda violada gera uma nova Entrega que nasce em Plan.
TRANSICOES: dict[Estado, frozenset[Estado]] = {
    Estado.PLAN: frozenset({Estado.DESIGN}),
    Estado.DESIGN: frozenset({Estado.AGUARDANDO_SPEC, Estado.BUILD}),
    Estado.AGUARDANDO_SPEC: frozenset({Estado.BUILD}),
    Estado.BUILD: frozenset({Estado.TEST}),
    Estado.TEST: frozenset({Estado.BUILD, Estado.REVIEW}),
    Estado.REVIEW: frozenset({Estado.BUILD, Estado.AGUARDANDO_HUMANO, Estado.DEPLOY}),
    Estado.AGUARDANDO_HUMANO: frozenset({Estado.DEPLOY}),
    Estado.DEPLOY: frozenset({Estado.MAINTAIN}),
    Estado.MAINTAIN: frozenset(),
}

LIMITE_PADRAO_DE_CICLOS = 3
