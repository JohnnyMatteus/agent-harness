#!/usr/bin/env python3
"""Lançador do CLI do Claude: é o `cli_path` que o Agent SDK executa.

O SDK mescla `os.environ` no ambiente do CLI e não deixa remover variáveis; por isso o CLI
nunca é executado direto. Este lançador (só stdlib, roda com o python do sistema) recompõe o
ambiente com uma allowlist, então segredo do worker (webhook, GitHub App, Redis) não chega ao
processo do agente nem a `/proc/self/environ` dele.

Modos (variável FORJA_AGENTE_MODO):
- host: executa o CLI real (FORJA_CLAUDE_CLI_REAL) com HOME descartável. Só para agente sem
  ferramenta nenhuma.
- docker: executa `claude` dentro do container do sandbox (FORJA_SANDBOX_CONTAINER) via
  `docker exec`; só os nomes da allowlist são repassados, os valores nunca vão em argv.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping, Sequence

PREFIXOS = ("CLAUDE_CODE_", "CLAUDE_AGENT_SDK_")
NOMES = frozenset(
    {"ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "TRACEPARENT", "TRACESTATE", "LANG", "LC_ALL"}
)
_CONTAINER = re.compile(r"forja-sbx-[A-Za-z0-9_-]{1,100}")


def ambiente_do_agente(origem: Mapping[str, str]) -> dict[str, str]:
    return {k: v for k, v in origem.items() if k in NOMES or k.startswith(PREFIXOS)}


def comando(
    modo: str, argv: Sequence[str], origem: Mapping[str, str]
) -> tuple[list[str], dict[str, str]]:
    """Devolve (argv, ambiente) do exec final."""
    permitido = ambiente_do_agente(origem)
    if modo == "host":
        real = origem["FORJA_CLAUDE_CLI_REAL"]
        ambiente = {**permitido, "PATH": "/usr/local/bin:/usr/bin:/bin"}
        ambiente["HOME"] = origem["FORJA_AGENTE_HOME"]
        return [real, *argv], ambiente
    if modo == "docker":
        container = origem["FORJA_SANDBOX_CONTAINER"]
        if not _CONTAINER.fullmatch(container):
            raise SystemExit("nome de container inválido")
        repassar = [x for nome in sorted(permitido) for x in ("-e", nome)]
        base = {
            k: origem[k] for k in ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONFIG") if k in origem
        }
        return (
            ["docker", "exec", "-i", "-w", "/workspace", *repassar, container, "claude", *argv],
            {**base, **permitido},
        )
    raise SystemExit("FORJA_AGENTE_MODO deve ser host ou docker")


def main() -> None:
    argv, ambiente = comando(os.environ.get("FORJA_AGENTE_MODO", ""), sys.argv[1:], os.environ)
    os.execvpe(argv[0], argv, ambiente)


if __name__ == "__main__":
    main()
