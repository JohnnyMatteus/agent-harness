"""Sessão de agente COM ferramentas (Executor): o CLI roda dentro do container do sandbox
(modo `docker` do lançador, ADR 0036) e todo uso de ferramenta passa pelo PreToolUse, que é
código determinístico (`forja.domain.guardrails`). Sem Bash: o shell é a ferramenta própria
`mcp__sandbox__exec`, que executa argv no container pelos mesmos guardrails; git é do workflow.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    HookContext,
    HookMatcher,
    McpSdkServerConfig,
    create_sdk_mcp_server,
    tool,
)

from forja.application.casos_de_uso.memoria_do_repositorio import MemoriaDoRepositorio
from forja.application.portas.sandbox import SandboxAtivo
from forja.domain.guardrails import (
    FERRAMENTA_EXEC,
    Decisao,
    PoliticaDeSessao,
    decidir_ferramenta,
)
from forja.domain.seguranca import redigir_segredos
from forja.infrastructure.agents.agent_sdk import LANCADOR
from forja.infrastructure.sandbox.docker import nome_container

FERRAMENTAS_NATIVAS = ["Read", "Glob", "Grep", "Write", "Edit"]
FERRAMENTA_MEMORIA = "mcp__memoria__memoria"
SAIDA_MAXIMA = 6_000
Bloqueio = Callable[[str, str], None]


def hook_pre_tool_use(politica: PoliticaDeSessao, ao_bloquear: Bloqueio | None = None) -> Any:
    """O ponto de entrada das ferramentas: nega por padrão tudo que a política não permite."""

    async def hook(entrada: Any, tool_use_id: str | None, contexto: HookContext) -> dict[str, Any]:
        nome = str(entrada.get("tool_name", ""))
        argumentos = entrada.get("tool_input")
        decisao: Decisao = decidir_ferramenta(
            politica,
            nome,
            argumentos if isinstance(argumentos, dict) else {},  # pyright: ignore[reportUnknownArgumentType]
        )
        if decisao.permitido:
            return {}
        if ao_bloquear is not None:
            ao_bloquear(nome, decisao.motivo)
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"bloqueado pela política da Forja: {decisao.motivo}",
            }
        }

    return hook


Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def tratador_exec(
    sandbox: SandboxAtivo, politica: PoliticaDeSessao, timeout_s: float = 300
) -> Handler:
    async def executar(args: dict[str, Any]) -> dict[str, Any]:
        # Reaplica a política: a ferramenta não depende de o hook ter rodado.
        d = decidir_ferramenta(politica, FERRAMENTA_EXEC, {"argv": args.get("argv")})
        if not d.permitido:
            return _texto(f"bloqueado: {d.motivo}", True)
        r = await sandbox.executar([str(a) for a in args["argv"]], timeout_s=timeout_s)
        corpo = f"saída {r.codigo_saida}\n{r.stdout[-SAIDA_MAXIMA:]}\n{r.stderr[-1500:]}"
        return _texto(corpo, r.codigo_saida != 0)

    return executar


def tratador_memoria(memoria: MemoriaDoRepositorio) -> Handler:
    async def executar(args: dict[str, Any]) -> dict[str, Any]:
        resposta = await memoria.executar(args)
        return _texto(resposta, resposta.startswith("Erro"))

    return executar


def servidor_exec(
    sandbox: SandboxAtivo, politica: PoliticaDeSessao, timeout_s: float = 300
) -> McpSdkServerConfig:
    ferramenta = tool(
        "exec",
        "Executa um comando no sandbox, sem shell. `argv` é a lista de argumentos.",
        {"argv": list[str]},
    )(tratador_exec(sandbox, politica, timeout_s))
    return create_sdk_mcp_server("sandbox", tools=[ferramenta])


def servidor_memoria(memoria: MemoriaDoRepositorio) -> McpSdkServerConfig:
    ferramenta = tool(
        "memoria",
        "Memória do repositório (view, create, str_replace, insert, delete, rename) em /memories.",
        {"command": str, "path": str, "file_text": str, "old_str": str, "new_str": str,
         "insert_line": int, "insert_text": str, "new_path": str},
    )(tratador_memoria(memoria))  # fmt: skip
    return create_sdk_mcp_server("memoria", tools=[ferramenta])


def _texto(texto: str, erro: bool) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": redigir_segredos(texto)}], "is_error": erro}


def opcoes_com_ferramentas(
    system_prompt: str,
    politica: PoliticaDeSessao,
    sandbox: SandboxAtivo,
    memoria: MemoriaDoRepositorio,
    cwd: Path,
    max_turnos: int,
    modelo: str | None = None,
    ao_bloquear: Bloqueio | None = None,
) -> ClaudeAgentOptions:
    """O CLI roda no container do sandbox; no host só há um diretório vazio e o lançador."""
    permitidas = [*FERRAMENTAS_NATIVAS, FERRAMENTA_EXEC, FERRAMENTA_MEMORIA]
    return ClaudeAgentOptions(
        system_prompt=system_prompt,
        tools=list(FERRAMENTAS_NATIVAS),
        allowed_tools=permitidas,
        disallowed_tools=["Bash", "WebFetch", "WebSearch", "NotebookEdit", "Task"],
        setting_sources=[],
        mcp_servers={
            "sandbox": servidor_exec(sandbox, politica),
            "memoria": servidor_memoria(memoria),
        },
        strict_mcp_config=True,
        hooks={
            "PreToolUse": [
                HookMatcher(
                    matcher=None,
                    hooks=[hook_pre_tool_use(politica, ao_bloquear)],
                    on_failure="block",
                )
            ]
        },
        permission_mode="dontAsk",
        cwd=str(cwd),
        max_turns=max_turnos,
        model=modelo,
        cli_path=str(LANCADOR),
        env={
            "FORJA_AGENTE_MODO": "docker",
            "FORJA_SANDBOX_CONTAINER": nome_container(sandbox.sessao_id),
        },
    )
