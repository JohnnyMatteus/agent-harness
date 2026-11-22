"""Configuração do domínio lida do ambiente (sem dependência de biblioteca)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass

from forja.domain.estados import LIMITE_PADRAO_DE_CICLOS

VARIAVEL_CICLOS = "FORJA_MAX_CICLOS_BUILD_TEST"


@dataclass(frozen=True, slots=True)
class Configuracao:
    max_ciclos_build_test: int = LIMITE_PADRAO_DE_CICLOS

    @classmethod
    def do_ambiente(cls, ambiente: Mapping[str, str] | None = None) -> "Configuracao":
        env = os.environ if ambiente is None else ambiente
        bruto = env.get(VARIAVEL_CICLOS)
        if bruto is None or not bruto.strip():
            return cls()
        try:
            valor = int(bruto)
        except ValueError as erro:
            raise ValueError(f"{VARIAVEL_CICLOS} deve ser um inteiro, veio {bruto!r}") from erro
        if valor < 1:
            raise ValueError(f"{VARIAVEL_CICLOS} deve ser pelo menos 1, veio {valor}")
        return cls(max_ciclos_build_test=valor)
