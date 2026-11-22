"""ACL do Claude Agent SDK: traduz mensagens do SDK para tipos do domínio (ADR 0010).

Só este módulo importa `claude_agent_sdk`. Em testes, injeta-se um `ClienteSdk` falso.
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Protocol

import claude_agent_sdk
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


# Redundância: `tools=[]` já remove todas as ferramentas nativas do CLI (`--tools ""`).
FERRAMENTAS_NEGADAS = ["Write", "Edit", "Bash", "NotebookEdit", "WebFetch", "Read", "Grep", "Glob"]
LANCADOR = Path(__file__).with_name("lancador_cli.py")


def cli_real() -> Path:
    return Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"


def opcoes_sem_ferramentas(
    system_prompt: str,
    cwd: Path,
    home: Path,
    max_turnos: int,
    modelo: str | None = None,
    lancador: Path = LANCADOR,
    cli: Path | None = None,
) -> ClaudeAgentOptions:
    """Agente sem ferramenta nenhuma, para texto não confiável (seção 9.4).

    - `tools=[]`: nenhuma ferramenta nativa (Read, Grep e Glob também somem);
    - `setting_sources=[]`: nem `.claude/settings.json`, nem CLAUDE.md, nem skills de usuário
      ou de repositório; `mcp_servers={}` + `strict_mcp_config`: nenhum MCP, nem `.mcp.json`;
    - `cwd` é um diretório vazio e descartável, nunca um repositório;
    - o ambiente do processo é recomposto pelo lançador (allowlist), sem segredo do worker.
    """
    return ClaudeAgentOptions(
        system_prompt=system_prompt,
        tools=[],
        allowed_tools=[],
        disallowed_tools=FERRAMENTAS_NEGADAS,
        setting_sources=[],
        mcp_servers={},
        strict_mcp_config=True,
        cwd=str(cwd),
        max_turns=max_turnos,
        model=modelo,
        cli_path=str(lancador),
        env={
            "FORJA_AGENTE_MODO": "host",
            "FORJA_CLAUDE_CLI_REAL": str(cli or cli_real()),
            "FORJA_AGENTE_HOME": str(home),
        },
    )


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

    @property
    def system_prompt(self) -> str:
        return self._system

    async def executar_com_opcoes(
        self, pedido: PedidoAgente, options: ClaudeAgentOptions
    ) -> RespostaDoAgente:
        """Sessão com ferramentas: as opções (CLI no sandbox, hooks, MCP) vêm de quem chama."""
        try:
            return await asyncio.wait_for(
                self._conversar(pedido, options), pedido.limites.timeout_s
            )
        except TimeoutError:
            raise LimiteExcedidoError(f"timeout de {pedido.limites.timeout_s}s excedido") from None

    async def _rodar(self, pedido: PedidoAgente) -> RespostaDoAgente:
        # cwd e HOME descartáveis: o texto do pedido é a única entrada do agente.
        with tempfile.TemporaryDirectory(prefix="forja-agente-") as raiz:
            cwd, home = Path(raiz) / "cwd", Path(raiz) / "home"
            cwd.mkdir()
            home.mkdir()
            options = opcoes_sem_ferramentas(
                self._system, cwd, home, pedido.limites.max_turnos, self._modelo
            )
            return await self._conversar(pedido, options)

    async def _conversar(
        self, pedido: PedidoAgente, options: ClaudeAgentOptions
    ) -> RespostaDoAgente:
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
