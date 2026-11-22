"""Memória por repositório (seção 6.4.2): `/memories/<repo>/` com arquivos curtos.

O que o agente escreve aqui volta ao prompt de sessões futuras: é um canal de persistência
para texto injetado. Por isso há tetos, saneamento e o texto sempre entra como dado.
"""

from __future__ import annotations

import re

from forja.domain.erros import ErroDeDominio
from forja.domain.seguranca import redigir_segredos

RAIZ = "/memories"
MAX_ARQUIVOS = 50
MAX_BYTES_POR_ARQUIVO = 8_000
MAX_BYTES_TOTAL = 100_000
_SEGMENTO = re.compile(
    r"[A-Za-z0-9_][A-Za-z0-9_. -]{0,60}\.(md|txt)|[A-Za-z0-9_][A-Za-z0-9_-]{0,40}"
)
_CONTROLE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class MemoriaInvalida(ErroDeDominio):
    """Caminho ou conteúdo de memória recusado."""


def caminho_de_memoria(caminho: object) -> str:
    """`/memories` -> ``""`` (raiz); `/memories/a/b.md` -> `a/b.md`. Nada fora de `/memories`."""
    if not isinstance(caminho, str) or len(caminho) > 200:
        raise MemoriaInvalida("caminho de memória inválido")
    if caminho == RAIZ or caminho == RAIZ + "/":
        return ""
    if not caminho.startswith(RAIZ + "/"):
        raise MemoriaInvalida("a memória vive só em /memories")
    partes = caminho[len(RAIZ) + 1 :].split("/")
    if len(partes) > 4 or any(_SEGMENTO.fullmatch(p) is None or p in (".", "..") for p in partes):
        raise MemoriaInvalida("segmento de caminho de memória inválido")
    return "/".join(partes)


def sanear_conteudo(texto: object) -> str:
    if not isinstance(texto, str):
        raise MemoriaInvalida("conteúdo deve ser texto")
    limpo = redigir_segredos(_CONTROLE.sub("", texto))
    if len(limpo.encode()) > MAX_BYTES_POR_ARQUIVO:
        raise MemoriaInvalida(f"arquivo de memória acima de {MAX_BYTES_POR_ARQUIVO} bytes")
    return limpo
