"""Maintain (seção 10.2): monitor de bandas e IncidentWorkflow.

O monitor consulta as bandas que o operador configurou para o repositório, em intervalos
fixos e, para cada violação, inicia
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
from temporalio.exceptions import ActivityError, WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from forja.application.portas.operacao import (
        AberturaDeIncidente,
        ConsultaDeMetricas,
        Diagnosticador,
        LeituraDeBandas,
    )
    from forja.domain.bandas import Banda, EstadoDaBanda, avaliar_banda, janela_avaliada
    from forja.domain.incidente import Evidencia
    from forja.infrastructure.telemetry.metricas import MetricasForja

JANELA_DO_INCIDENTE_S = 3600
ESTADO_DESATIVADO = "desativado"  # o repositório saiu da lista do operador: o monitor para
INTERVALO_MINIMO_S = 30.0
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


@dataclass(frozen=True)
class DiagnosticoDto:
    titulo: str
    corpo: str
    incident_md: str
    custo_usd: float = 0.0


@dataclass(frozen=True)
class AberturaEntrada:
    repositorio: str
    banda_id: str
    titulo: str
    corpo: str


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
        repositorios: frozenset[str],
        passo_s: int = 60,
        telemetria: MetricasForja | None = None,
    ) -> None:
        self._bandas = bandas
        self._metricas = metricas
        self._diagnostico = diagnostico
        self._incidentes = incidentes
        self._repositorios = repositorios  # a lista do operador, relida a cada activity
        self._passo = passo_s
        self._telemetria = telemetria

    def _permitido(self, repositorio: str) -> bool:
        return repositorio in self._repositorios

    @activity.defn(name="checar_bandas")
    async def checar_bandas(self, repositorio: str) -> list[VerificacaoDto]:
        """Uma verificação por banda. Falha fechada: configuração ausente, vazia ou ilegível,
        erro de consulta, resposta parcial, série vazia ou com NaN viram `sem_dados` (e são
        ditos), nunca `dentro` nem lista vazia. Repositório que saiu da lista do operador vira
        `desativado`, e o monitor para."""
        if not self._permitido(repositorio):
            return [
                VerificacaoDto("*", ESTADO_DESATIVADO, "repositório fora de FORJA_MONITOR_REPOS")
            ]
        try:
            bandas = await self._bandas.bandas(repositorio)
        except Exception as erro:
            return [self._sem_dados("*", f"bandas ilegíveis ({type(erro).__name__})")]
        if bandas is None or not bandas.bandas:
            return [self._sem_dados("*", "bandas não configuradas para este repositório")]
        resultados: list[VerificacaoDto] = []
        for b in bandas.bandas:
            fim = _agora()  # o mesmo instante vale para a consulta e para a avaliação
            try:
                serie = await self._metricas.serie(
                    b.consulta, b.por_segundos + 2 * self._passo, self._passo, fim
                )
            except Exception as erro:
                resultados.append(self._sem_dados(b.id, f"consulta falhou ({type(erro).__name__})"))
                continue
            estado, motivo = avaliar_banda(b, serie, fim, self._passo)
            if estado is EstadoDaBanda.SEM_DADOS:
                resultados.append(self._sem_dados(b.id, motivo))
                continue
            e = Evidencia.da_serie(b, janela_avaliada(b, serie, fim))
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

    def _sem_dados(self, banda_id: str, motivo: str) -> VerificacaoDto:
        activity.logger.warning("banda %s sem dados: %s", banda_id, motivo)
        if self._telemetria is not None:
            self._telemetria.bandas_sem_dados.inc()
        return VerificacaoDto(banda_id, EstadoDaBanda.SEM_DADOS, motivo[:200])

    @activity.defn(name="diagnosticar_incidente")
    async def diagnosticar(self, e: IncidenteEntrada) -> DiagnosticoDto:
        """A única atividade paga (LLM). O workflow a chama uma vez por janela, sem retentar."""
        v = e.violacao
        if not self._permitido(e.repositorio):
            raise ValueError("repositório fora de FORJA_MONITOR_REPOS")
        if v.estado != EstadoDaBanda.VIOLADA:
            raise ValueError("só uma banda violada abre incidente")
        banda = Banda(v.banda_id, v.consulta, v.maximo, v.por_segundos)
        evidencia = Evidencia(v.banda_id, v.maximo, v.por_segundos, v.atual, v.pico, v.amostras)
        deploys = await self._bandas.deploys_recentes(e.repositorio)
        resultado = await self._diagnostico.diagnosticar(e.repositorio, banda, evidencia, deploys)
        uso = resultado.uso
        if self._telemetria is not None:  # o custo é medido mesmo que a issue falhe depois
            self._telemetria.diagnosticos.inc()
            self._telemetria.custo_usd.inc(uso.custo_usd)
            self._telemetria.tokens.labels("entrada").inc(uso.tokens_entrada)
            self._telemetria.tokens.labels("saida").inc(uso.tokens_saida)
        i = resultado.valor
        return DiagnosticoDto(
            f"Incidente: banda {v.banda_id} violada",
            i.corpo_da_issue(),
            i.incident_md(),
            uso.custo_usd,
        )

    @activity.defn(name="abrir_incidente")
    async def abrir_incidente(self, e: AberturaEntrada) -> str:
        """Só abre a issue (idempotente, uma por banda aberta); falhar não paga o LLM de novo."""
        if not self._permitido(e.repositorio):
            raise ValueError("repositório fora de FORJA_MONITOR_REPOS")
        chave = f"{e.repositorio}:{e.banda_id}:{activity.info().workflow_id}"
        return await self._incidentes.abrir(
            e.repositorio, e.titulo, e.corpo, hashlib.sha256(chave.encode()).hexdigest()[:24]
        )


def _agora() -> float:
    import time

    return time.time()


def id_do_incidente(repositorio: str, banda_id: str, agora: float) -> str:
    janela = int(agora // JANELA_DO_INCIDENTE_S)
    resumo = hashlib.sha256(f"{repositorio}:{banda_id}".encode()).hexdigest()[:16]
    return f"incidente-{resumo}-{janela}"


@workflow.defn(name="IncidentWorkflow")
class IncidentWorkflow:
    """Uma tentativa paga por janela: o diagnóstico (LLM) não é retentado, e o id do filho só
    vale uma vez por janela (REJECT_DUPLICATE). Abrir a issue é retentável e idempotente, e
    falhar nela não paga o diagnóstico de novo (o texto fica no histórico deste workflow)."""

    @workflow.run
    async def run(self, entrada: IncidenteEntrada) -> IncidenteSaida:
        d = await workflow.execute_activity(
            "diagnosticar_incidente",
            entrada,
            result_type=DiagnosticoDto,
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        issue = await workflow.execute_activity(
            "abrir_incidente",
            AberturaEntrada(entrada.repositorio, entrada.violacao.banda_id, d.titulo, d.corpo),
            result_type=str,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=5, non_retryable_error_types=NAO_REPETIR),
        )
        return IncidenteSaida(entrada.violacao.banda_id, issue, d.incident_md, d.custo_usd)


def intervalo_valido(segundos: float) -> float:
    """Finito e entre 30 s e 24 h; o que não for vira o mínimo (NaN incluso)."""
    if not segundos >= INTERVALO_MINIMO_S:
        return INTERVALO_MINIMO_S
    return min(segundos, 24 * 3600.0)


@workflow.defn(name="MonitorDeBandas")
class MonitorDeBandas:
    def __init__(self) -> None:
        self._parar = False

    @workflow.signal
    def parar(self) -> None:
        self._parar = True

    @workflow.run
    async def run(self, entrada: MonitorEntrada) -> MonitorSaida:
        """Nunca morre por falha de activity (nem por activity não registrada ou timeout):
        registra `sem_dados`, espera e segue. Só para com o sinal ou se o repositório saiu da
        lista do operador."""
        saida = MonitorSaida()
        for _ in range(entrada.iteracoes_por_execucao):
            if self._parar:
                return saida
            try:
                verificacoes: list[VerificacaoDto] = await workflow.execute_activity(
                    "checar_bandas",
                    entrada.repositorio,
                    result_type=list[VerificacaoDto],
                    start_to_close_timeout=timedelta(minutes=5),
                    schedule_to_close_timeout=timedelta(minutes=15),
                    retry_policy=RetryPolicy(
                        maximum_attempts=3, non_retryable_error_types=NAO_REPETIR
                    ),
                )
            except ActivityError as erro:
                workflow.logger.warning("checar_bandas falhou: %s", type(erro.cause).__name__)
                verificacoes = [
                    VerificacaoDto(
                        "*",
                        EstadoDaBanda.SEM_DADOS,
                        f"activity falhou ({type(erro.cause).__name__})",
                    )
                ]
            saida.verificacoes += 1
            if any(v.estado == ESTADO_DESATIVADO for v in verificacoes):
                return saida
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
                        # Uma tentativa por janela: um filho que falhou não é refeito até a
                        # janela seguinte, senão cada intervalo pagaria outro diagnóstico.
                        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                        parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                    )
                    saida.incidentes_iniciados.append(wid)
                except WorkflowAlreadyStartedError:
                    pass  # já existe (ou já falhou) um incidente desta banda nesta janela
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(
                    lambda: self._parar,
                    timeout=timedelta(seconds=intervalo_valido(entrada.intervalo_s)),
                )
        workflow.continue_as_new(entrada)
