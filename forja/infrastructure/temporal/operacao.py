"""Maintain (seção 10.2): monitor de bandas e IncidentWorkflow.

O monitor consulta as bandas do repositório em intervalos fixos e, para cada violação, inicia
um IncidentWorkflow com id determinístico por (repositório, banda, janela): a mesma violação não
abre dois incidentes. O incidente diagnostica e abre uma issue `forja:incident`; quem aplica
`forja:intent` é um humano (portão), então o ciclo volta ao Plan sem agir sozinho.
"""

from __future__ import annotations

import contextlib
import hashlib
from dataclasses import dataclass, field
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from forja.application.portas.operacao import (
        AberturaDeIncidente,
        ConsultaDeMetricas,
        Diagnosticador,
        LeituraDeBandas,
    )
    from forja.domain.bandas import Banda, BandasInvalidas, EstadoDaBanda, avaliar_banda
    from forja.domain.incidente import Evidencia

JANELA_DO_INCIDENTE_S = 3600
NAO_REPETIR = ["BandasInvalidas", "PrometheusIndisponivel", "SaidaInvalida", "ValueError"]


@dataclass(frozen=True)
class VerificacaoDto:
    """Resultado de uma banda: `violada`, `dentro` ou `sem_dados` (com o motivo, gerado por
    código). `sem_dados` nunca é "tudo bem" e nunca abre incidente."""

    banda_id: str
    estado: str
    motivo: str = ""
    consulta: str = ""
    maximo: float = 0.0
    por_segundos: int = 0
    atual: float = 0.0
    pico: float = 0.0
    amostras: int = 0


@dataclass(frozen=True)
class MonitorEntrada:
    repositorio: str
    intervalo_s: float = 300.0
    iteracoes_por_execucao: int = 288  # 1 dia a cada 5 min; depois continue_as_new


@dataclass(frozen=True)
class IncidenteEntrada:
    repositorio: str
    violacao: VerificacaoDto


@dataclass
class IncidenteSaida:
    banda_id: str
    issue: str = ""
    incident_md: str = ""
    custo_usd: float = 0.0


@dataclass
class MonitorSaida:
    verificacoes: int = 0
    incidentes_iniciados: list[str] = field(default_factory=list[str])
    # "banda: motivo" da última verificação sem dados: o monitor mostra o que não conseguiu ver.
    sem_dados: list[str] = field(default_factory=list[str])


class AtividadesDeOperacao:
    def __init__(
        self,
        bandas: LeituraDeBandas,
        metricas: ConsultaDeMetricas,
        diagnostico: Diagnosticador,
        incidentes: AberturaDeIncidente,
        passo_s: int = 60,
    ) -> None:
        self._bandas = bandas
        self._metricas = metricas
        self._diagnostico = diagnostico
        self._incidentes = incidentes
        self._passo = passo_s

    @activity.defn(name="checar_bandas")
    async def checar_bandas(self, repositorio: str) -> list[VerificacaoDto]:
        """Uma verificação por banda. Falha fechada: configuração ilegível, erro de consulta,
        resposta parcial, série vazia ou com NaN viram `sem_dados` (e são ditos), nunca `dentro`.
        Sem bandas configuradas para o repositório não há o que monitorar."""
        try:
            bandas = await self._bandas.bandas(repositorio)
        except BandasInvalidas as erro:
            return [VerificacaoDto("*", EstadoDaBanda.SEM_DADOS, f"bandas ilegíveis: {erro}"[:200])]
        if bandas is None:
            return []
        resultados: list[VerificacaoDto] = []
        for b in bandas.bandas:
            try:
                serie = await self._metricas.serie(
                    b.consulta, b.por_segundos + 2 * self._passo, self._passo
                )
            except Exception as erro:
                activity.logger.warning("banda %s sem dados: %s", b.id, type(erro).__name__)
                resultados.append(
                    VerificacaoDto(
                        b.id, EstadoDaBanda.SEM_DADOS, f"consulta falhou: {type(erro).__name__}"
                    )
                )
                continue
            estado, motivo = avaliar_banda(b, serie, _agora(), self._passo)
            if estado is EstadoDaBanda.SEM_DADOS:
                resultados.append(VerificacaoDto(b.id, estado, motivo))
                continue
            e = Evidencia.da_serie(b, serie)
            resultados.append(
                VerificacaoDto(
                    b.id,
                    estado,
                    "",
                    b.consulta,
                    b.maximo,
                    b.por_segundos,
                    e.atual,
                    e.pico,
                    e.amostras,
                )
            )
        return resultados

    @activity.defn(name="diagnosticar_e_abrir_incidente")
    async def diagnosticar_e_abrir(self, e: IncidenteEntrada) -> IncidenteSaida:
        v = e.violacao
        if v.estado != EstadoDaBanda.VIOLADA:
            raise ValueError("só uma banda violada abre incidente")
        banda = Banda(v.banda_id, v.consulta, v.maximo, v.por_segundos)
        evidencia = Evidencia(v.banda_id, v.maximo, v.por_segundos, v.atual, v.pico, v.amostras)
        deploys = await self._bandas.deploys_recentes(e.repositorio)
        resultado = await self._diagnostico.diagnosticar(e.repositorio, banda, evidencia, deploys)
        incidente = resultado.valor
        chave = f"{e.repositorio}:{v.banda_id}:{activity.info().workflow_id}"
        issue = await self._incidentes.abrir(
            e.repositorio,
            f"Incidente: banda {v.banda_id} violada",
            incidente.corpo_da_issue(),
            hashlib.sha256(chave.encode()).hexdigest()[:24],
        )
        return IncidenteSaida(v.banda_id, issue, incidente.incident_md(), resultado.uso.custo_usd)


def _agora() -> float:
    import time

    return time.time()


def id_do_incidente(repositorio: str, banda_id: str, agora: float) -> str:
    janela = int(agora // JANELA_DO_INCIDENTE_S)
    resumo = hashlib.sha256(f"{repositorio}:{banda_id}".encode()).hexdigest()[:16]
    return f"incidente-{resumo}-{janela}"


@workflow.defn(name="IncidentWorkflow")
class IncidentWorkflow:
    @workflow.run
    async def run(self, entrada: IncidenteEntrada) -> IncidenteSaida:
        return await workflow.execute_activity(
            "diagnosticar_e_abrir_incidente",
            entrada,
            result_type=IncidenteSaida,
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=3, non_retryable_error_types=NAO_REPETIR),
        )


@workflow.defn(name="MonitorDeBandas")
class MonitorDeBandas:
    def __init__(self) -> None:
        self._parar = False

    @workflow.signal
    def parar(self) -> None:
        self._parar = True

    @workflow.run
    async def run(self, entrada: MonitorEntrada) -> MonitorSaida:
        saida = MonitorSaida()
        for _ in range(entrada.iteracoes_por_execucao):
            if self._parar:
                return saida
            verificacoes: list[VerificacaoDto] = await workflow.execute_activity(
                "checar_bandas",
                entrada.repositorio,
                result_type=list[VerificacaoDto],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3, non_retryable_error_types=NAO_REPETIR),
            )
            saida.verificacoes += 1
            saida.sem_dados = [
                f"{v.banda_id}: {v.motivo}"
                for v in verificacoes
                if v.estado == EstadoDaBanda.SEM_DADOS
            ]
            for v in verificacoes:
                if v.estado != EstadoDaBanda.VIOLADA:
                    continue  # dentro, ou sem dados (que não abre incidente, só é dito)
                wid = id_do_incidente(entrada.repositorio, v.banda_id, workflow.now().timestamp())
                try:
                    await workflow.start_child_workflow(
                        IncidentWorkflow.run,
                        IncidenteEntrada(entrada.repositorio, v),
                        id=wid,
                        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                        parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                    )
                    saida.incidentes_iniciados.append(wid)
                except WorkflowAlreadyStartedError:
                    pass  # já existe um incidente desta banda nesta janela
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(
                    lambda: self._parar, timeout=timedelta(seconds=entrada.intervalo_s)
                )
        workflow.continue_as_new(entrada)
