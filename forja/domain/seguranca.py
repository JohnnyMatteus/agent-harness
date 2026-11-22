"""Saneamento de texto e identificadores que vêm de fora (issue, comentário, modelo).

Conteúdo externo nunca vira instrução, caminho ou argumento sem passar por aqui (seção 9.4).
"""

import re

_REPOSITORIO = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9_.][A-Za-z0-9_.-]{0,99}")
_MENCAO = re.compile(r"@(?=[A-Za-z0-9_])")
LIMITE_COMENTARIO = 6000


def repositorio_valido(repositorio: str) -> bool:
    """Forma `dono/nome` sem `..`, sem barras extras e sem caracteres de shell."""
    return _REPOSITORIO.fullmatch(repositorio) is not None and ".." not in repositorio


def neutralizar_texto(texto: str, limite: int = LIMITE_COMENTARIO) -> str:
    """Texto que será publicado: sem menções (notificariam terceiros), sem HTML nem marcadores
    de comentário forjados, e com tamanho limitado."""
    seguro = _MENCAO.sub("@​", texto.replace("<", "&lt;"))
    if len(seguro) > limite:
        return seguro[: limite - 1] + "…"
    return seguro
