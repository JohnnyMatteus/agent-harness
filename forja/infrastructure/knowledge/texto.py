"""Tokenização compartilhada: o mesmo texto vira os mesmos termos no índice e na consulta."""

from __future__ import annotations

import re

_PALAVRA = re.compile(r"[A-Za-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def termos(texto: str) -> list[str]:
    """camelCase vira partes; snake_case já é separado pelo sublinhado; o termo inteiro fica."""
    saida: list[str] = []
    for palavra in _PALAVRA.findall(texto):
        partes = [p.lower() for p in _CAMEL.split(palavra) if p]
        saida.append(palavra.lower())
        if len(partes) > 1:
            saida.extend(partes)
    return saida


def texto_de_busca(texto: str) -> str:
    return " ".join(termos(texto))
