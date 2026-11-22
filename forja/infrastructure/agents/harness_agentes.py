"""Inicializador e Executor do harness (seção 5.3)."""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import ValidationError

from forja.application.casos_de_uso.memoria_do_repositorio import MemoriaDoRepositorio
from forja.application.portas.agente import LimitesSessao, PedidoAgente, UsoModelo
from forja.application.portas.harness import PlanoInicial, PropostaDeContrato, ResultadoDeSessao
from forja.application.portas.sandbox import SandboxAtivo
from forja.domain.guardrails import Etapa, PoliticaDeSessao, decidir_comando
from forja.domain.harness import (
    LIMIARES_PROVISORIOS,
    ContratoDeSprint,
    Feature,
    FeatureList,
    comando_de_teste_valido,
)
from forja.domain.seguranca import dado_nao_confiavel
from forja.infrastructure.agents.agent_sdk import AgentSdkRunner
from forja.infrastructure.agents.esquemas import ContratoSaida, InicializacaoSaida, SessaoSaida
from forja.infrastructure.agents.estruturado import (
    AgenteEstruturado,
    SaidaInvalida,
    extrair_json,
)
from forja.infrastructure.agents.sessao_com_ferramentas import Bloqueio, opcoes_com_ferramentas
from forja.infrastructure.telemetry.otel import registrar_uso, span_sessao_agente


class InicializadorAgente:
    def __init__(self, agente: AgenteEstruturado[InicializacaoSaida]) -> None:
        self._agente = agente

    async def inicializar(self, repositorio: str, spec_md: str, plano_md: str) -> PlanoInicial:
        texto = (
            f"<spec>{dado_nao_confiavel(spec_md)}</spec>\n"
            f"<plano>{dado_nao_confiavel(plano_md)}</plano>"
        )
        politica = PoliticaDeSessao(Etapa.EXECUTOR, "0" * 16)

        def converter(s: InicializacaoSaida) -> tuple[FeatureList, tuple[tuple[str, ...], ...]]:
            lista = FeatureList(
                tuple(
                    Feature(
                        f.id,
                        f.categoria,
                        f.descricao,
                        tuple(f.passos_de_teste),
                        tuple(f.comando_de_teste),
                    )
                    for f in s.features
                ),
                comando_de_teste_valido(tuple(s.comando_de_fumaca)),
            )
            for comando in s.comandos_de_setup:
                d = decidir_comando(politica, comando)
                if not d.permitido:
                    raise ValueError(f"comando de setup recusado: {d.motivo}")
            return lista, tuple(tuple(c) for c in s.comandos_de_setup)

        (lista, setup), uso = await self._agente.pedir(repositorio, texto, converter)
        return PlanoInicial(lista, setup, lista.comando_de_fumaca, uso)


class ExecutorAgente:
    def __init__(
        self,
        runner: AgentSdkRunner,
        contratante: AgenteEstruturado[ContratoSaida],
        memoria: Callable[[str], MemoriaDoRepositorio],
        modelo: str | None = None,
        max_turnos: int = 40,
        timeout_s: float = 1800,
        ao_bloquear: Bloqueio | None = None,
    ) -> None:
        self._runner = runner
        self._contratante = contratante
        self._memoria = memoria
        self._modelo = modelo
        self._max_turnos = max_turnos
        self._timeout = timeout_s
        self._ao_bloquear = ao_bloquear

    async def propor_contrato(
        self, repositorio: str, bloco: int, features: Sequence[Feature], ajustes: Sequence[str]
    ) -> PropostaDeContrato:
        texto = (
            "<funcionalidades>\n"
            + "\n".join(f"- {f.id}: {dado_nao_confiavel(f.descricao)}" for f in features)
            + "\n</funcionalidades>"
        )
        if ajustes:
            texto += "\n<ajustes>" + dado_nao_confiavel("\n".join(ajustes)) + "</ajustes>"

        def converter(s: ContratoSaida) -> ContratoDeSprint:
            return ContratoDeSprint(
                bloco, tuple(s.features), tuple(s.entregaveis), tuple(s.verificacao),
                LIMIARES_PROVISORIOS,
            )  # fmt: skip

        contrato, uso = await self._contratante.pedir(repositorio, texto, converter)
        return PropostaDeContrato(contrato, uso)

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
        memoria = self._memoria(repositorio)
        texto = (
            f"<intent_id>{intent_id}</intent_id>\n"
            f'<funcionalidade id="{feature.id}">{dado_nao_confiavel(feature.descricao)}\n'
            f"passos de teste: {dado_nao_confiavel('; '.join(feature.passos_de_teste))}\n"
            f"comando de teste: {' '.join(feature.comando_de_teste)}</funcionalidade>\n"
            f"<contexto>{dado_nao_confiavel(contexto)}</contexto>\n"
            f"<memoria_do_repositorio>{await memoria.para_o_prompt()}</memoria_do_repositorio>"
        )
        if feedback:
            texto += (
                f"\n<feedback_do_avaliador>{dado_nao_confiavel(feedback)}</feedback_do_avaliador>"
            )
        with tempfile.TemporaryDirectory(prefix="forja-exec-") as raiz:
            opcoes = opcoes_com_ferramentas(
                self._runner.system_prompt,
                politica, sandbox, memoria, Path(raiz), self._max_turnos, self._modelo,
                self._ao_bloquear,
            )  # fmt: skip
            pedido = PedidoAgente(texto, limites=LimitesSessao(self._timeout, self._max_turnos))
            with span_sessao_agente(
                intent_id, {"forja.papel": "executor", "forja.feature": feature.id}
            ) as span:
                resposta = await self._runner.executar_com_opcoes(pedido, opcoes)
                registrar_uso(span, resposta.uso)
        try:
            saida = SessaoSaida.model_validate(extrair_json(resposta.texto))
        except (ValueError, ValidationError) as erro:
            raise SaidaInvalida(
                f"executor: resposta final fora do schema ({type(erro).__name__})"
            ) from erro
        return ResultadoDeSessao(saida.mensagem_de_commit, saida.resumo, resposta.uso)


def uso_zero() -> UsoModelo:
    return UsoModelo()
