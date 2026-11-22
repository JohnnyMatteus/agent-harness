"""`python -m forja.interfaces.mcp`: servidor MCP knowledge via stdio, escopo do token da sessão."""

import os
import sys

from forja.infrastructure.knowledge.configuracao import ConfiguracaoInvalida
from forja.interfaces.mcp.composicao import servidor_do_ambiente


def main() -> int:
    try:
        servidor = servidor_do_ambiente(os.environ)
    except ConfiguracaoInvalida as erro:
        sys.stderr.write(f"knowledge: {erro}\n")
        return 2
    servidor.run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
