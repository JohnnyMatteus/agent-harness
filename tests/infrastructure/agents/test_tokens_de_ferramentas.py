# pyright: basic
"""Medição (ADR 0046, M7): quantos tokens de definição de ferramenta cada agente recebe hoje.

É ESTIMATIVA: caracteres do JSON da definição / 4. Serve para comparar com a mesma régua, não é a
contagem do tokenizador. Fica de fora o que não é nosso e não medimos: as definições das cinco
ferramentas nativas do CLI (Read, Glob, Grep, Write, Edit) e o texto interno da ferramenta de
memória da Messages API. Se este teste falhar por estourar o limiar, reavalie o tool search
(regra de quando ligar no ADR 0046), não aumente o limite.
"""

import json
import math
from typing import Any

from forja.infrastructure.agents import avaliador as av
from forja.infrastructure.agents import sessao_com_ferramentas as sf

CARACTERES_POR_TOKEN = 4
# Anthropic recomenda tool search a partir de ~10 ferramentas ou ~10 mil tokens de definições.
LIMIAR_DE_FERRAMENTAS = 10
LIMIAR_DE_TOKENS = 10_000


def tokens(definicao: dict) -> int:
    texto = json.dumps(definicao, ensure_ascii=False)
    return math.ceil(len(texto) / CARACTERES_POR_TOKEN)


async def definicoes_mcp_do_executor() -> list[dict]:
    """O que o CLI recebe dos servidores MCP em processo, como o SDK as publica (tools/list)."""
    servidores = {
        "sandbox": sf.servidor_exec(None, None),  # type: ignore[arg-type]
        "memoria": sf.servidor_memoria(None),  # type: ignore[arg-type]
        "skills": sf.servidor_skills(None),  # type: ignore[arg-type]
    }
    definicoes = []
    for nome, config in servidores.items():
        entrada = config["instance"]._request_handlers["tools/list"]
        resposta: Any = await entrada.handler(None, entrada.params_type())  # pyright: ignore
        for t in resposta.tools:
            definicoes.append(
                {"name": f"mcp__{nome}__{t.name}", "description": t.description,
                 "input_schema": t.input_schema}
            )  # fmt: skip
    return definicoes


def definicoes_do_avaliador() -> list[dict]:
    return [*av.FERRAMENTAS, av.FERRAMENTA_FINAL_AVALIACAO]


async def test_o_executor_recebe_oito_ferramentas_e_as_nossas_somam_poucas_centenas_de_tokens():
    mcp = await definicoes_mcp_do_executor()
    assert [d["name"] for d in mcp] == [
        "mcp__sandbox__exec",
        "mcp__memoria__memoria",
        "mcp__skills__skill",
    ]
    assert len(sf.FERRAMENTAS_NATIVAS) + len(mcp) == 8
    total = sum(tokens(d) for d in mcp)
    assert 200 <= total <= 320  # medido: 254 (exec 63, memoria 140, skill 51)
    assert len(mcp) < LIMIAR_DE_FERRAMENTAS and total < LIMIAR_DE_TOKENS // 10


def test_o_avaliador_recebe_quatro_ferramentas_e_somam_poucas_centenas_de_tokens():
    defs = definicoes_do_avaliador()
    assert [d["name"] for d in defs] == [
        "memory", "executar_comando", "ler_arquivo", "registrar_avaliacao",
    ]  # fmt: skip
    total = sum(tokens(d) for d in defs)
    assert 180 <= total <= 260  # medido: 219 (12 + 62 + 43 + 102)
    assert len(defs) < LIMIAR_DE_FERRAMENTAS and total < LIMIAR_DE_TOKENS // 10


def test_interprete_spec_planner_revisores_e_diagnostico_nao_recebem_ferramenta_nenhuma():
    """`tools=[]` e as ferramentas de escrita negadas: zero tokens de definição (ver test_eco e
    test_diagnostico, que verificam as opções reais)."""
    from forja.infrastructure.agents.agent_sdk import FERRAMENTAS_NEGADAS

    assert {"Write", "Edit", "Bash", "Read", "Grep", "Glob"} <= set(FERRAMENTAS_NEGADAS)


async def test_com_o_conjunto_atual_a_busca_sob_demanda_nao_compensa():
    """A ferramenta de busca é, ela mesma, uma definição a mais em todo turno; com menos de dez
    ferramentas e centenas de tokens ela custaria perto do que economiza (ADR 0046)."""
    mcp = await definicoes_mcp_do_executor()
    assert sum(tokens(d) for d in mcp) < LIMIAR_DE_TOKENS // 10
