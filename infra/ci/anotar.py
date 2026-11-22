"""Transforma saídas de passos que falharam em até 5 anotações `::error` do GitHub Actions.

Uso: anotar.py <titulo> <rotulo=arquivo>...   Lê só os arquivos indicados; nunca o ambiente.
"""

import re
import sys
from pathlib import Path

LIMITE = 3000  # caracteres por anotação, antes de escapar (o limite do GitHub é 4 KB)
RELEVANTE = re.compile(r"^(FAILED|ERROR|E\s|.*Error|.*falhou|.*FATAL)")


def escapar(texto: str) -> str:
    return texto.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def trecho(linhas: list[str]) -> str:
    relevantes = [x for x in linhas if RELEVANTE.match(x)]
    escolhidas = [*relevantes[:25], "...", *linhas[-15:]] if relevantes else linhas[-30:]
    return "\n".join(escolhidas)[-LIMITE:]


def main(argv: list[str]) -> None:
    titulo = argv[1]
    for item in argv[2:7]:
        rotulo, _, caminho = item.partition("=")
        arq = Path(caminho)
        if not arq.is_file() or arq.stat().st_size == 0:
            continue
        linhas = arq.read_text(errors="replace").splitlines()
        print(f"::error title={titulo}::{escapar(rotulo + chr(10) + trecho(linhas))}")


if __name__ == "__main__":
    main(sys.argv)
