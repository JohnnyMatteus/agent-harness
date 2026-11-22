"""Portas do Maintain (seção 10.2): métricas, bandas, diagnóstico e abertura de incidentes."""

from __future__ import annotations

from typing import Protocol

from forja.application.portas.sdlc import Resultado
from forja.domain.bandas import Amostra, Banda, Bandas
from forja.domain.incidente import Evidencia, Incidente


class ConsultaDeMetricas(Protocol):
    async def serie(self, consulta: str, janela_s: int, passo_s: int) -> list[Amostra]:
        """Série de uma consulta PromQL somente leitura (a consulta vem do repositório)."""
        ...


class LeituraDeDeploys(Protocol):
    async def deploys_recentes(self, repositorio: str) -> list[str]:
        """Últimos commits da branch padrão. É dado do repositório: vai ao prompt delimitado."""
        ...


class LeituraDeBandas(LeituraDeDeploys, Protocol):
    async def bandas(self, repositorio: str) -> Bandas | None:
        """Bandas do OPERADOR para o repositório (nunca lidas do repositório); None se não há."""
        ...


class Diagnosticador(Protocol):
    async def diagnosticar(
        self, repositorio: str, banda: Banda, evidencia: Evidencia, deploys: list[str]
    ) -> Resultado[Incidente]: ...


class AberturaDeIncidente(Protocol):
    async def abrir(self, repositorio: str, titulo: str, corpo: str, chave: str) -> str:
        """Abre a issue do incidente (label `forja:incident`) uma vez por `chave`. Devolve a URL
        ou "dry-run"."""
        ...
