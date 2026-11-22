"""`python -m forja.interfaces.cli.indexar`: indexa um checkout no Postgres, só o que mudou."""

import argparse
import json
import os
import sys
from pathlib import Path

from forja.application.casos_de_uso.indexar_repositorio import IndexarRepositorio
from forja.domain.knowledge import Escopo
from forja.infrastructure.knowledge.chunker import ChunkerEstrutural
from forja.infrastructure.knowledge.configuracao import (
    VARIAVEL_BANCO,
    ConfiguracaoInvalida,
    embedder_do_ambiente,
    exigir,
)
from forja.infrastructure.knowledge.contexto import ContextoPorEstrutura
from forja.infrastructure.knowledge.postgres import IndicePostgres
from forja.infrastructure.knowledge.varredura import VarreduraDeDiretorio


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="indexar")
    parser.add_argument("--raiz", type=Path, required=True)
    parser.add_argument("--org", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args(argv)
    try:
        embedder = embedder_do_ambiente(os.environ)
        indice = IndicePostgres(exigir(os.environ, VARIAVEL_BANCO))
    except ConfiguracaoInvalida as erro:
        sys.stderr.write(f"indexar: {erro}\n")
        return 2
    indice.garantir_esquema(embedder.dimensao)
    relatorio = IndexarRepositorio(
        VarreduraDeDiretorio(args.raiz, args.commit),
        ChunkerEstrutural(),
        embedder,
        ContextoPorEstrutura(),
        indice,
    ).executar(Escopo(args.org, args.repo))
    sys.stdout.write(
        json.dumps(
            {
                "indexados": relatorio.indexados,
                "inalterados": relatorio.inalterados,
                "removidos": relatorio.removidos,
                "trechos": relatorio.trechos,
                "recusados": relatorio.recusados,
            }
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
