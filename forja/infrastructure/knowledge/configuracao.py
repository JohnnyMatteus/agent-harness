"""Configuração do Knowledge lida do ambiente."""

from __future__ import annotations

from collections.abc import Mapping

from forja.application.portas.knowledge import Embedder
from forja.infrastructure.knowledge.embedder_falso import EmbedderFalso

VARIAVEL_EMBEDDER = "FORJA_EMBEDDER"
VARIAVEL_DIMENSAO = "FORJA_EMBEDDER_DIMENSAO"
VARIAVEL_BANCO = "DATABASE_URL"


class ConfiguracaoInvalida(Exception):
    """Variável ausente ou valor não suportado; o processo deve falhar em vez de improvisar."""


def exigir(ambiente: Mapping[str, str], nome: str) -> str:
    valor = ambiente.get(nome, "").strip()
    if not valor:
        raise ConfiguracaoInvalida(f"variavel {nome} ausente")
    return valor


def embedder_do_ambiente(ambiente: Mapping[str, str]) -> Embedder:
    """Só o embedder falso existe hoje, e só por escolha explícita: não há default silencioso.

    Um adaptador de embedding real (provedor e credencial) é decisão pendente do autor.
    """
    nome = exigir(ambiente, VARIAVEL_EMBEDDER)
    if nome != "falso":
        raise ConfiguracaoInvalida(
            f"{VARIAVEL_EMBEDDER}={nome!r} nao suportado: ainda nao ha adaptador de embedding real"
        )
    try:
        return EmbedderFalso(int(ambiente.get(VARIAVEL_DIMENSAO, "64")))
    except ValueError as erro:
        raise ConfiguracaoInvalida(f"{VARIAVEL_DIMENSAO} precisa ser inteiro") from erro
