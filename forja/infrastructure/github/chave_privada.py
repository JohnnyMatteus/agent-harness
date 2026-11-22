from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from forja.infrastructure.github.erros import GitHubAuthError

VAR_CHAVE = "FORJA_GITHUB_APP_PRIVATE_KEY"
VAR_ARQUIVO = "FORJA_GITHUB_APP_PRIVATE_KEY_FILE"


def carregar_chave_privada(env: Mapping[str, str] | None = None) -> str:
    """Lê o PEM do ambiente ou de um arquivo montado (secret); nunca do repositório."""
    env = os.environ if env is None else env
    if caminho := env.get(VAR_ARQUIVO):
        try:
            return Path(caminho).read_text()
        except OSError as erro:
            raise GitHubAuthError(f"não foi possível ler {VAR_ARQUIVO}") from erro
    if valor := env.get(VAR_CHAVE):
        return valor.replace("\\n", "\n")
    raise GitHubAuthError(f"defina {VAR_CHAVE} ou {VAR_ARQUIVO}")
