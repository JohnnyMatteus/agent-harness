"""Saneamento de texto e identificadores que vêm de fora (issue, comentário, modelo).

Conteúdo externo nunca vira instrução, caminho ou argumento sem passar por aqui (seção 9.4).
"""

import re

_REPOSITORIO = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9_.][A-Za-z0-9_.-]{0,99}")
_MENCAO = re.compile(r"@(?=[A-Za-z0-9_])")
_IMAGEM = re.compile(r"!\[[^\]]*\](?:\([^)]*\)|\[[^\]]*\])")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_DEFINICAO = re.compile(r"^[ \t]*\[[^\]]+\]:[ \t]*\S.*$", re.MULTILINE)
_SEGREDO = re.compile(
    r"(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w+|sk-[A-Za-z0-9_-]{16,}|Bearer\s+\S+"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
LIMITE_COMENTARIO = 6000


def repositorio_valido(repositorio: str) -> bool:
    """Forma `dono/nome` sem `..`, sem barras extras e sem caracteres de shell."""
    return _REPOSITORIO.fullmatch(repositorio) is not None and ".." not in repositorio


def redigir_segredos(texto: str) -> str:
    return _SEGREDO.sub("[REDIGIDO]", texto)


def neutralizar_texto(texto: str, limite: int = LIMITE_COMENTARIO) -> str:
    """Texto que será publicado. Fecha os canais de saída que um texto injetado pode abrir:
    menções (notificam terceiros), HTML e marcadores forjados, imagens e links markdown e URLs
    (o GitHub busca imagens sozinho, então `![](https://x/?dados)` vaza dados), segredos."""
    seguro = redigir_segredos(texto).replace("<", "&lt;")
    for _ in range(3):  # aninhamento como `![a](u)` dentro de `[..](u)`
        seguro = _IMAGEM.sub("[imagem removida]", seguro)
        seguro = _LINK.sub(r"\1 (link removido)", seguro)
        seguro = _DEFINICAO.sub("[definição removida]", seguro)
    # Sobras de aninhamento: sem `](` nem `![` nenhuma sintaxe de link ou imagem se forma.
    seguro = seguro.replace("](", "] (").replace("![", "! [")
    seguro = seguro.replace("://", ":\u200b//").replace("www.", "www\u200b.")
    seguro = _MENCAO.sub("@\u200b", seguro)
    if len(seguro) > limite:
        return seguro[: limite - 1] + "…"
    return seguro
