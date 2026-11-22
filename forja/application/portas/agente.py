"""Porta do agente: o domínio só enxerga estes tipos, nunca os do Agent SDK (ADR 0010)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class AgenteError(Exception):
    """Sessão de agente encerrada de forma explícita (timeout, teto de turnos, erro do SDK)."""


class LimiteExcedidoError(AgenteError):
    pass


@dataclass(frozen=True)
class LimitesSessao:
    timeout_s: float = 120.0
    max_turnos: int = 5


@dataclass(frozen=True)
class UsoModelo:
    tokens_entrada: int = 0
    tokens_saida: int = 0
    custo_usd: float = 0.0


@dataclass(frozen=True)
class PedidoAgente:
    texto_nao_confiavel: str
    # Só agentes com ferramenta usam o diretório (dentro do sandbox); o eco não toca em arquivo.
    diretorio_trabalho: Path | None = None
    limites: LimitesSessao = LimitesSessao()


@dataclass(frozen=True)
class RespostaDoAgente:
    texto: str
    uso: UsoModelo = UsoModelo()
    turnos: int = 0


class AgentRunner(Protocol):
    async def executar(self, pedido: PedidoAgente) -> RespostaDoAgente: ...
