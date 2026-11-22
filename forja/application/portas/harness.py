"""Portas do harness de longa duração (seção 5.3): Inicializador, Executor, Avaliador."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from forja.application.portas.agente import UsoModelo
from forja.application.portas.sandbox import SandboxAtivo
from forja.domain.guardrails import PoliticaDeSessao
from forja.domain.harness import ContratoDeSprint, Criterio, Feature, FeatureList


@dataclass(frozen=True, slots=True)
class ContextoDaEntrega:
    repositorio: str
    intent_id: str
    branch: str
    run_id: str = ""


@dataclass(frozen=True, slots=True)
class ResultadoDoBloco:
    contrato: ContratoDeSprint
    aprovadas: tuple[str, ...]
    reprovadas: tuple[str, ...]
    aprovado_pelo_avaliador: bool
    feedback: str
    completa: bool
    violacoes: tuple[str, ...] = ()
    uso: UsoModelo = field(default_factory=UsoModelo)


@dataclass(frozen=True, slots=True)
class ResultadoDaVerificacao:
    verde: bool
    resultados: dict[str, bool]


@dataclass(frozen=True, slots=True)
class PlanoInicial:
    """O que o Inicializador propõe: a lista de funcionalidades e os comandos de ambiente."""

    features: FeatureList
    comandos_de_setup: tuple[tuple[str, ...], ...]
    comando_de_fumaca: tuple[str, ...]
    uso: UsoModelo = field(default_factory=UsoModelo)


@dataclass(frozen=True, slots=True)
class ResultadoDeSessao:
    mensagem_de_commit: str
    resumo: str
    uso: UsoModelo = field(default_factory=UsoModelo)


@dataclass(frozen=True, slots=True)
class PropostaDeContrato:
    contrato: ContratoDeSprint
    uso: UsoModelo = field(default_factory=UsoModelo)


@dataclass(frozen=True, slots=True)
class RevisaoDoContrato:
    acordo: bool
    ajustes: tuple[str, ...]
    uso: UsoModelo = field(default_factory=UsoModelo)


@dataclass(frozen=True, slots=True)
class Avaliacao:
    notas: Mapping[Criterio, int]
    feedback: Mapping[Criterio, str]
    defeitos: tuple[str, ...]
    uso: UsoModelo = field(default_factory=UsoModelo)


@dataclass(frozen=True, slots=True)
class PedidoDeAvaliacao:
    contrato: ContratoDeSprint
    intent_md: str
    spec_md: str
    plano_md: str
    resumo_das_sessoes: str
    resultados_dos_testes: Mapping[str, bool]


class Inicializador(Protocol):
    async def inicializar(self, repositorio: str, spec_md: str, plano_md: str) -> PlanoInicial: ...


class ExecutorDeSessao(Protocol):
    async def propor_contrato(
        self, repositorio: str, bloco: int, features: Sequence[Feature], ajustes: Sequence[str]
    ) -> PropostaDeContrato: ...

    async def executar_sessao(
        self,
        sandbox: SandboxAtivo,
        repositorio: str,
        intent_id: str,
        feature: Feature,
        contexto: str,
        feedback: str,
        politica: PoliticaDeSessao,
    ) -> ResultadoDeSessao:
        """Uma funcionalidade por sessão. O agente só edita arquivos e roda comandos de teste;
        o git é do workflow."""
        ...


class AvaliadorIndependente(Protocol):
    async def revisar_contrato(
        self, repositorio: str, contrato: ContratoDeSprint
    ) -> RevisaoDoContrato: ...

    async def avaliar(
        self, sandbox: SandboxAtivo, repositorio: str, pedido: PedidoDeAvaliacao
    ) -> Avaliacao: ...


class Harness(Protocol):
    """O Build de longa duração como as activities o enxergam."""

    async def inicializar(
        self, ctx: ContextoDaEntrega, spec_md: str, plano_md: str
    ) -> tuple[FeatureList, UsoModelo]: ...

    async def executar_bloco(
        self, ctx: ContextoDaEntrega, bloco: int, artefatos: dict[str, str], feedback: str
    ) -> ResultadoDoBloco: ...

    async def verificar(self, ctx: ContextoDaEntrega) -> ResultadoDaVerificacao: ...
