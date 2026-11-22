from __future__ import annotations

from forja.application.portas.knowledge import Particao


class ContextoPorEstrutura:
    """Prefixo determinístico a partir de caminho, símbolo e linguagem; não chama modelo.

    A geração por modelo (ADR 0013) entra por outra implementação da mesma porta.
    """

    versao = "contexto-estrutural-1"

    def contexto(self, caminho: str, simbolo: str | None, particao: Particao) -> str:
        alvo = f"símbolo {simbolo} " if simbolo else ""
        return f"{particao.tipo.value} {particao.linguagem}: {alvo}em {caminho}"
