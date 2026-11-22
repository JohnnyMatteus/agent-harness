"""ACL do Claude Agent SDK: traduz mensagens do SDK para tipos do domínio (ADR 0010).

Só este módulo importa `claude_agent_sdk`. Em testes, injeta-se um `ClienteSdk` falso.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Protocol

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

from forja.application.portas.agente import (
    AgenteError,
    LimiteExcedidoError,
    PedidoAgente,
    RespostaDoAgente,
    UsoModelo,
)


class ClienteSdk(Protocol):
    def __call__(self, *, prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[Any]: ...


# Ferramentas de escrita nunca são concedidas ao agente (texto não confiável, seção 9.4).
FERRAMENTAS_PERMITIDAS: list[str] = []
FERRAMENTAS_NEGADAS = ["Write", "Edit", "Bash", "NotebookEdit", "WebFetch"]


class AgentSdkRunner:
    def __init__(
        self, system_prompt: str, cliente: ClienteSdk = query, modelo: str | None = None
    ) -> None:
        self._system = system_prompt
        self._cliente = cliente
        self._modelo = modelo

    async def executar(self, pedido: PedidoAgente) -> RespostaDoAgente:
        try:
            return await asyncio.wait_for(self._rodar(pedido), pedido.limites.timeout_s)
        except TimeoutError:
            raise LimiteExcedidoError(f"timeout de {pedido.limites.timeout_s}s excedido") from None

    async def _rodar(self, pedido: PedidoAgente) -> RespostaDoAgente:
        options = ClaudeAgentOptions(
            system_prompt=self._system,
            cwd=str(pedido.diretorio_trabalho),
            max_turns=pedido.limites.max_turnos,
            allowed_tools=FERRAMENTAS_PERMITIDAS,
            disallowed_tools=FERRAMENTAS_NEGADAS,
            model=self._modelo,
        )
        prompt = f"<pedido_nao_confiavel>\n{pedido.texto_nao_confiavel}\n</pedido_nao_confiavel>"
        textos: list[str] = []
        try:
            async for msg in self._cliente(prompt=prompt, options=options):
                if isinstance(msg, AssistantMessage):
                    textos += [b.text for b in msg.content if isinstance(b, TextBlock)]
                elif isinstance(msg, ResultMessage):
                    return _traduzir(msg, textos)
        except AgenteError:
            raise
        except Exception as exc:
            raise AgenteError(f"falha no Agent SDK: {type(exc).__name__}") from exc
        raise AgenteError("sessão terminou sem mensagem de resultado")


def _traduzir(msg: ResultMessage, textos: list[str]) -> RespostaDoAgente:
    if msg.subtype == "error_max_turns":
        raise LimiteExcedidoError(f"teto de {msg.num_turns} turnos excedido")
    if msg.is_error:
        raise AgenteError(f"sessão terminou com erro: {msg.subtype}")
    uso: dict[str, Any] = msg.usage or {}
    return RespostaDoAgente(
        texto=msg.result or "\n".join(textos),
        uso=UsoModelo(
            tokens_entrada=int(uso.get("input_tokens", 0)),
            tokens_saida=int(uso.get("output_tokens", 0)),
            custo_usd=float(msg.total_cost_usd or 0.0),
        ),
        turnos=msg.num_turns,
    )
