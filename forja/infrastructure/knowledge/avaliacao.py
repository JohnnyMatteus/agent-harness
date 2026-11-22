"""Avaliação do RAG com corpus inventado e embeddings falsos: mede o encanamento, não um modelo.

Uso: `python -m forja.infrastructure.knowledge.avaliacao [--atualizar]`.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from forja.application.casos_de_uso.indexar_repositorio import IndexarRepositorio
from forja.application.casos_de_uso.recuperar_conhecimento import RecuperarConhecimento
from forja.domain.knowledge import Escopo
from forja.infrastructure.knowledge.chunker import ChunkerEstrutural
from forja.infrastructure.knowledge.contexto import ContextoPorEstrutura
from forja.infrastructure.knowledge.embedder_falso import EmbedderFalso
from forja.infrastructure.knowledge.memoria import IndiceEmMemoria
from forja.infrastructure.knowledge.varredura import VarreduraDeDiretorio

RAIZ_DO_EVAL = Path(__file__).resolve().parents[3] / "evals" / "rag"
VERSAO_DAS_METRICAS = 1
KS = (1, 3, 5)
AVISO = (
    "Embeddings falsos (hash de termos) e corpus inventado: valida o pipeline e detecta "
    "regressao de chunking, fusao e isolamento. Nao diz nada sobre a qualidade de um modelo real."
)


@dataclass(frozen=True, slots=True)
class Pergunta:
    texto: str
    caminho: str
    simbolo: str


def sha_do_eval(raiz: Path = RAIZ_DO_EVAL) -> str:
    """Muda se o corpus ou as perguntas mudarem: a baseline precisa ser renovada de propósito."""
    resumo = hashlib.sha256()
    for arquivo in sorted((raiz / "corpus").rglob("*")):
        if arquivo.is_file():
            resumo.update(arquivo.relative_to(raiz).as_posix().encode())
            resumo.update(arquivo.read_bytes())
    resumo.update((raiz / "perguntas.json").read_bytes())
    return resumo.hexdigest()


def carregar_perguntas(raiz: Path = RAIZ_DO_EVAL) -> list[Pergunta]:
    dados = json.loads((raiz / "perguntas.json").read_text(encoding="utf-8"))
    return [Pergunta(p["pergunta"], p["caminho"], p["simbolo"]) for p in dados["perguntas"]]


def avaliar(raiz: Path = RAIZ_DO_EVAL) -> dict[str, object]:
    escopo = Escopo("ficticia", "armazem")
    indice = IndiceEmMemoria()
    embedder = EmbedderFalso(64)
    IndexarRepositorio(
        VarreduraDeDiretorio(raiz / "corpus", "corpus-inventado"),
        ChunkerEstrutural(),
        embedder,
        ContextoPorEstrutura(),
        indice,
    ).executar(escopo)
    recuperador = RecuperarConhecimento(indice, embedder)

    perguntas = carregar_perguntas(raiz)
    posicoes: list[int | None] = []
    for p in perguntas:
        pagina = recuperador.buscar(escopo, p.texto, limite=max(KS))
        posicoes.append(
            next(
                (
                    i
                    for i, r in enumerate(pagina.itens, start=1)
                    if (r.trecho.caminho, r.trecho.simbolo) == (p.caminho, p.simbolo)
                ),
                None,
            )
        )
    n = len(perguntas)
    metricas: dict[str, float] = {
        f"recall@{k}": round(sum(1 for x in posicoes if x is not None and x <= k) / n, 4)
        for k in KS
    }
    metricas["mrr"] = round(sum(1 / x for x in posicoes if x) / n, 4)
    return {
        "versao_metricas": VERSAO_DAS_METRICAS,
        "embedder": embedder.versao,
        "pipeline": f"{ChunkerEstrutural.versao}+{embedder.versao}+{ContextoPorEstrutura.versao}",
        "corpus_sha": sha_do_eval(raiz),
        "perguntas": n,
        "metricas": metricas,
        "aviso": AVISO,
    }


def regressoes(baseline: Mapping[str, object], atual: Mapping[str, object]) -> list[str]:
    """Métricas que caíram em relação à baseline. Melhorar não é erro; piorar bloqueia."""
    antigas = cast(dict[str, float], baseline["metricas"])
    novas = cast(dict[str, float], atual["metricas"])
    return [
        f"{nome}: {antigas[nome]} -> {novas.get(nome)}"
        for nome in antigas
        if novas.get(nome, 0.0) < antigas[nome]
    ]


def main(argv: list[str]) -> int:
    resultado = avaliar()
    texto = json.dumps(resultado, indent=2, ensure_ascii=False) + "\n"
    if "--atualizar" in argv:
        (RAIZ_DO_EVAL / "baseline.json").write_text(texto, encoding="utf-8")
    sys.stdout.write(texto)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
