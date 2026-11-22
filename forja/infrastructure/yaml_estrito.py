"""Leitor estrito de um subconjunto de YAML, para `.forja/policy.yaml` e o arquivo de bandas
do operador.

O arquivo pode vir do repositório-alvo (policy.yaml: conteúdo não confiável). Aceita só:
mapeamentos e listas em blocos (indentação de espaços), listas de escalares em linha
(`[a, "b"]`) e escalares (texto, aspas, número, true/false/null). Recusa âncoras, tags, documentos múltiplos, blocos
`|`/`>`, tabulação e aninhamento acima de 8 níveis. Não há dependência YAML no projeto:
quando houver (PyYAML com `safe_load`), este módulo sai. Decisão registrada no ADR 0042.
"""

from __future__ import annotations

import re
from typing import Any

MAX_BYTES = 64_000
MAX_NIVEIS = 8
_CHAVE = re.compile(r"([A-Za-z0-9_][A-Za-z0-9_.-]*):(?:\s+(.*))?$")
_INTEIRO = re.compile(r"-?\d+")
_DECIMAL = re.compile(r"-?\d+\.\d+")


class YamlInvalido(ValueError):
    """Arquivo fora do subconjunto aceito."""


def ler(texto: str) -> Any:
    if len(texto.encode()) > MAX_BYTES:
        raise YamlInvalido("arquivo acima do teto de tamanho")
    linhas: list[tuple[int, str, int]] = []
    for n, bruta in enumerate(texto.splitlines(), 1):
        if "\t" in bruta:
            raise YamlInvalido(f"linha {n}: tabulação não é permitida")
        sem_comentario = _sem_comentario(bruta)
        if not sem_comentario.strip():
            continue
        recuo = len(sem_comentario) - len(sem_comentario.lstrip(" "))
        linhas.append((recuo, sem_comentario.strip(), n))
    if not linhas:
        return {}
    if linhas[0][1].startswith("---"):
        raise YamlInvalido("marcador de documento não é permitido")
    valor, fim = _bloco(linhas, 0, linhas[0][0], 1)
    if fim != len(linhas):
        raise YamlInvalido(f"linha {linhas[fim][2]}: indentação inesperada")
    return valor


def _sem_comentario(linha: str) -> str:
    aspas = ""
    for i, c in enumerate(linha):
        if aspas:
            if c == aspas:
                aspas = ""
        elif c in "\"'":
            aspas = c
        elif c == "#" and (i == 0 or linha[i - 1] == " "):
            return linha[:i].rstrip()
    return linha.rstrip()


def _bloco(linhas: list[tuple[int, str, int]], i: int, recuo: int, nivel: int) -> tuple[Any, int]:
    if nivel > MAX_NIVEIS:
        raise YamlInvalido("aninhamento acima do teto")
    if linhas[i][1].startswith("- ") or linhas[i][1] == "-":
        return _lista(linhas, i, recuo, nivel)
    return _mapa(linhas, i, recuo, nivel)


def _mapa(linhas: list[tuple[int, str, int]], i: int, recuo: int, nivel: int) -> tuple[Any, int]:
    mapa: dict[str, Any] = {}
    while i < len(linhas) and linhas[i][0] == recuo and not linhas[i][1].startswith("- "):
        _, texto, n = linhas[i]
        achado = _CHAVE.match(texto)
        if achado is None:
            raise YamlInvalido(f"linha {n}: esperava `chave: valor`")
        chave, resto = achado.group(1), achado.group(2)
        if chave in mapa:
            raise YamlInvalido(f"linha {n}: chave repetida {chave!r}")
        i += 1
        if resto:
            mapa[chave] = _escalar(resto, n)
        elif i < len(linhas) and (
            linhas[i][0] > recuo or (linhas[i][0] == recuo and linhas[i][1].startswith("- "))
        ):
            mapa[chave], i = _bloco(linhas, i, linhas[i][0], nivel + 1)
        else:
            mapa[chave] = None
    return mapa, i


def _lista(linhas: list[tuple[int, str, int]], i: int, recuo: int, nivel: int) -> tuple[Any, int]:
    itens: list[Any] = []
    while (
        i < len(linhas)
        and linhas[i][0] == recuo
        and (linhas[i][1].startswith("- ") or linhas[i][1] == "-")
    ):
        _, texto, n = linhas[i]
        conteudo = texto[2:].strip()
        if conteudo and _CHAVE.match(conteudo):  # item é um mapeamento: `- chave: valor`
            sub = [(recuo + 2, conteudo, n)]
            j = i + 1
            while j < len(linhas) and linhas[j][0] > recuo:
                sub.append(linhas[j])
                j += 1
            mapa, fim = _mapa(sub, 0, recuo + 2, nivel + 1)
            if fim != len(sub):
                raise YamlInvalido(f"linha {sub[fim][2]}: indentação inesperada no item")
            itens.append(mapa)
            i = j
        elif conteudo:
            itens.append(_escalar(conteudo, n))
            i += 1
        else:
            raise YamlInvalido(f"linha {n}: item de lista vazio")
    return itens, i


def _escalar(texto: str, n: int) -> Any:
    if texto[0] in "&*!|>%@`{":
        raise YamlInvalido(f"linha {n}: âncora, tag, bloco ou mapeamento em linha não permitido")
    if texto[0] == "[":
        if not texto.endswith("]"):
            raise YamlInvalido(f"linha {n}: lista em linha sem fechar")
        return [_escalar(p, n) for p in _dividir(texto[1:-1], n)]
    if texto[0] in "\"'":
        if len(texto) < 2 or texto[-1] != texto[0]:
            raise YamlInvalido(f"linha {n}: aspas sem fechar")
        return texto[1:-1]
    if texto in ("true", "false"):
        return texto == "true"
    if texto in ("null", "~"):
        return None
    if _INTEIRO.fullmatch(texto):
        return int(texto)
    if _DECIMAL.fullmatch(texto):
        return float(texto)
    return texto


def _dividir(interior: str, n: int) -> list[str]:
    if not interior.strip():
        return []
    partes: list[str] = []
    atual, aspas = "", ""
    for c in interior:
        if aspas:
            atual += c
            if c == aspas:
                aspas = ""
        elif c in "\"'":
            aspas = c
            atual += c
        elif c == ",":
            partes.append(atual.strip())
            atual = ""
        elif c in "[]{}":
            raise YamlInvalido(f"linha {n}: aninhamento em linha não permitido")
        else:
            atual += c
    if aspas:
        raise YamlInvalido(f"linha {n}: aspas sem fechar")
    partes.append(atual.strip())
    if any(not p for p in partes):
        raise YamlInvalido(f"linha {n}: elemento vazio na lista")
    return partes
