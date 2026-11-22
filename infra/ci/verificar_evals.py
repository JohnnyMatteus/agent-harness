"""Gate das evals de regressão: lê o JUnit XML do pytest e FALHA se algo não rodou de verdade.

Uso: verificar_evals.py <junit.xml> [minimo_de_testes]

Regra: zero testes executados, qualquer falha, erro ou skip, ou menos testes que o mínimo =
falha. Nunca é verde por ter pulado. Lê só o arquivo indicado; nunca o ambiente.
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def problemas(xml: str, minimo: int = 1) -> list[str]:
    try:
        raiz = ET.fromstring(xml)
    except ET.ParseError as erro:
        return [f"junit ilegível: {erro}"]
    suites = [raiz] if raiz.tag == "testsuite" else list(raiz.iter("testsuite"))
    total = sum(int(s.get("tests", 0)) for s in suites)
    achados: list[str] = []
    if total == 0:
        achados.append("nenhum teste rodou: zero tarefas é falha, não sucesso")
    elif total < minimo:
        achados.append(f"só {total} testes rodaram; o mínimo é {minimo}")
    for nome in ("failures", "errors", "skipped"):
        n = sum(int(s.get(nome, 0)) for s in suites)
        if n:
            achados.append(f"{n} {nome}: em regressão, qualquer {nome[:-1]} é falha")
    return achados


def main(argv: list[str]) -> int:
    if not 1 <= len(argv) <= 2:
        print("uso: verificar_evals.py <junit.xml> [minimo_de_testes]", file=sys.stderr)
        return 2
    try:
        texto = Path(argv[0]).read_text(encoding="utf-8")
        minimo = int(argv[1]) if len(argv) == 2 else 1
    except (OSError, ValueError) as erro:
        print(f"::error::gate das evals: {erro}")
        return 1
    achados = problemas(texto, minimo)
    for a in achados:
        print(f"::error::gate das evals: {a}")
    if not achados:
        print("gate das evals: tudo rodou e passou")
    return 1 if achados else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
