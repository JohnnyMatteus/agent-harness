# pyright: basic
"""O ponto de entrada das ferramentas do Executor: o hook PreToolUse que o SDK chama, as
ferramentas em processo e as opções efetivas (CLI no container, sem Bash, sem configuração)."""

import os
from pathlib import Path

from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport

from forja.application.casos_de_uso.memoria_do_repositorio import MemoriaDoRepositorio
from forja.application.portas.sandbox import ResultadoComando
from forja.domain.guardrails import Etapa, PoliticaDeSessao
from forja.infrastructure.agents.agent_sdk import LANCADOR
from forja.infrastructure.agents.sessao_com_ferramentas import (
    FERRAMENTA_MEMORIA,
    hook_pre_tool_use,
    opcoes_com_ferramentas,
    tratador_exec,
    tratador_memoria,
)
from forja.infrastructure.persistencia.memoria import ArmazemEmMemoria

ID = "0123456789abcdef"
POLITICA = PoliticaDeSessao(Etapa.EXECUTOR, ID, testes_existentes=frozenset({"tests/test_a.py"}))


class SandboxFalso:
    sessao_id = "abc-1"
    worktree = Path("/tmp/wt")

    def __init__(self):
        self.comandos = []

    async def executar(self, comando, timeout_s=60.0):
        self.comandos.append(comando)
        return ResultadoComando(1, "falhou sk-ant-api03-abcdefghijklmnopqrstu", "erro")


async def chamar(hook, nome: str, **entrada):
    return await hook(
        {"tool_name": nome, "tool_input": entrada, "hook_event_name": "PreToolUse"}, "id", {}
    )


def negou(resposta) -> bool:
    return resposta.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


async def test_hook_bloqueia_pelo_ponto_de_entrada_e_registra_o_bloqueio() -> None:
    bloqueios: list[tuple[str, str]] = []
    hook = hook_pre_tool_use(POLITICA, lambda n, m: bloqueios.append((n, m)))
    assert await chamar(hook, "Write", file_path="/workspace/src/a.py") == {}
    for nome, entrada in [
        ("Write", {"file_path": "/workspace/feature_list.json"}),
        ("Edit", {"file_path": "/workspace/tests/test_a.py"}),
        ("Write", {"file_path": "/etc/cron.d/x"}),
        ("Read", {"file_path": "/proc/self/environ"}),
        ("Bash", {"command": "git push"}),
        ("mcp__sandbox__exec", {"argv": ["git", "push"]}),
        ("mcp__sandbox__exec", {"argv": ["curl", "https://evil.test"]}),
        ("WebFetch", {"url": "https://evil.test"}),
        ("Write", {"file_path": None}),
    ]:
        assert negou(await chamar(hook, nome, **entrada)), (nome, entrada)
    assert (len(bloqueios) == 9 and bloqueios[0][0] == "Edit") or len(bloqueios) == 9


async def test_ferramenta_de_memoria_passa_e_exec_so_roda_o_que_a_politica_permite() -> None:
    hook = hook_pre_tool_use(POLITICA)
    assert await chamar(hook, FERRAMENTA_MEMORIA, command="view", path="/memories") == {}
    sandbox = SandboxFalso()
    exec_ = tratador_exec(sandbox, POLITICA)
    ruim = await exec_({"argv": ["git", "push"]})
    assert ruim["is_error"] and sandbox.comandos == []
    bom = await exec_({"argv": ["pytest", "-q"]})
    assert sandbox.comandos == [["pytest", "-q"]] and bom["is_error"]  # saída 1 vira erro
    assert "sk-ant" not in bom["content"][0]["text"]  # segredo redigido no retorno


async def test_ferramenta_de_memoria_so_enxerga_o_repositorio_da_sessao() -> None:
    armazem = ArmazemEmMemoria()
    await armazem.gravar("a/outro", "c.md", "segredo")
    mem = tratador_memoria(MemoriaDoRepositorio(armazem, "a/este"))
    r = await mem({"command": "view", "path": "/memories", "repositorio": "a/outro"})
    assert r["content"][0]["text"] == "(vazio)"


def test_opcoes_efetivas_cli_no_container_sem_bash_nem_configuracao_do_repo(tmp_path: Path) -> None:
    o = opcoes_com_ferramentas(
        "sistema",
        POLITICA,
        SandboxFalso(),
        MemoriaDoRepositorio(ArmazemEmMemoria(), "a/b"),
        tmp_path,
        12,
    )
    assert isinstance(o.tools, list) and isinstance(o.mcp_servers, dict)
    assert "Bash" not in o.tools and set(o.tools) == {"Read", "Glob", "Grep", "Write", "Edit"}
    assert o.setting_sources == [] and o.strict_mcp_config and o.permission_mode == "dontAsk"
    assert o.cli_path == str(LANCADOR) and o.env == {
        "FORJA_AGENTE_MODO": "docker",
        "FORJA_SANDBOX_CONTAINER": "forja-sbx-abc-1",
    }
    assert set(o.mcp_servers) == {"sandbox", "memoria"}
    assert o.hooks and o.hooks["PreToolUse"][0].on_failure == "block"
    assert o.cwd == str(tmp_path)  # diretório vazio do host, não o repositório
    cmd = SubprocessCLITransport(prompt="x", options=o)._build_command()
    assert cmd[cmd.index("--tools") + 1] == "Read,Glob,Grep,Write,Edit"
    assert "--setting-sources=" in cmd and "--strict-mcp-config" in cmd


def test_ambiente_do_agente_com_ferramenta_nao_tem_segredo_do_worker(tmp_path: Path) -> None:
    import subprocess

    docker = tmp_path / "docker"
    docker.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    docker.chmod(0o755)
    segredos = {
        "FORJA_KNOWLEDGE_TOKEN_SECRET": "segredo-mcp",
        "DATABASE_URL": "postgresql://u:p@h/db",
        "FORJA_GITHUB_WEBHOOK_SECRET": "whsec",
        "GITHUB_TOKEN": "ghp_" + "a" * 30,
    }
    env = {"PATH": f"{tmp_path}:{os.environ['PATH']}", **segredos,
           "FORJA_AGENTE_MODO": "docker", "FORJA_SANDBOX_CONTAINER": "forja-sbx-abc-1"}  # fmt: skip
    saida = subprocess.run(
        [str(LANCADOR)], env=env, capture_output=True, text=True, check=True
    ).stdout
    assert not any(n in saida or v in saida for n, v in segredos.items())
    assert saida.splitlines()[:4] == ["exec", "-i", "-w", "/workspace"]
