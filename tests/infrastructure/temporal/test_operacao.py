# pyright: basic
"""Maintain: monitor de bandas e IncidentWorkflow com Temporal de teste e dublês."""

import contextlib
import time

import pytest
import pytest_asyncio
from temporalio.client import Client
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import Worker

from forja.application.portas.sdlc import Resultado
from forja.domain.artefatos import Fonte
from forja.domain.bandas import Amostra, Bandas, BandasInvalidas
from forja.domain.incidente import Incidente
from forja.infrastructure.telemetry.prometheus import PrometheusIndisponivel
from forja.infrastructure.temporal.operacao import (
    AtividadesDeOperacao,
    IncidenteEntrada,
    IncidentWorkflow,
    MonitorDeBandas,
    MonitorEntrada,
    VerificacaoDto,
    id_do_incidente,
)

BANDAS = Bandas.de_dict(
    {"service": "s", "bands": [{"id": "lat", "query": "q-lat", "max": 0.3, "for": "5m"},
                               {"id": "dlq", "query": "q-dlq", "max": 0.1, "for": "5m"}]}
)  # fmt: skip


@pytest_asyncio.fixture
async def env():
    # Um servidor por teste: o monitor continua-como-novo, e um run esquecido travaria o
    # time-skipping do teste seguinte.
    async with await WorkflowEnvironment.start_time_skipping() as e:
        yield e


class FonteDeBandas:
    def __init__(self, bandas=BANDAS):
        self.bandas_ = bandas

    async def bandas(self, repositorio):
        return self.bandas_

    async def deploys_recentes(self, repositorio):
        return ["abc123 2026-11-22 feat: x"]


class Metricas:
    def __init__(self, violadas: set[str], falhar: Exception | None = None, serie_fixa=None):
        self.violadas, self.falhar, self.serie_fixa = violadas, falhar, serie_fixa
        self.consultas: list[str] = []

    async def serie(self, consulta, janela_s, passo_s):
        self.consultas.append(consulta)
        if self.falhar:
            raise self.falhar
        if self.serie_fixa is not None:
            return self.serie_fixa
        valor = 0.9 if consulta.removeprefix("q-") in self.violadas else 0.01
        agora = time.time()
        return [Amostra(agora - (10 - i) * passo_s, valor) for i in range(11)]


class Diagnostico:
    def __init__(self):
        self.chamadas = []

    async def diagnosticar(self, repositorio, banda, evidencia, deploys):
        self.chamadas.append((banda.id, deploys))
        return Resultado(
            Incidente(
                evidencia,
                "causa provável: deploy",
                "reverter",
                ("pico 0.9",),
                (Fonte("i", "docs/runbook.md", "c" * 40),),
            )
        )


class Incidentes:
    def __init__(self):
        self.abertos = []

    async def abrir(self, repositorio, titulo, corpo, chave):
        self.abertos.append((titulo, corpo, chave))
        return "https://github.test/issues/9"


async def rodar(env, metricas, bandas=None, iteracoes=3):
    diag, inc = Diagnostico(), Incidentes()
    fila = f"op-{time.time_ns()}"  # cada teste a sua fila: o monitor continua-como-novo sem parar
    ativ = AtividadesDeOperacao(bandas or FonteDeBandas(), metricas, diag, inc, passo_s=60)
    async with Worker(
        env.client, task_queue=fila, workflows=[MonitorDeBandas, IncidentWorkflow],
        activities=[ativ.checar_bandas, ativ.diagnosticar_e_abrir],
    ):  # fmt: skip
        h = await env.client.start_workflow(
            MonitorDeBandas.run, MonitorEntrada("acme/loja", 300, iteracoes),
            id=f"mon-{time.time_ns()}", task_queue=fila,
        )  # fmt: skip
        fim = "concluiu"
        try:  # continue_as_new ao fim das iterações
            await h.result(follow_runs=False)
        except Exception as erro:
            fim = type(erro).__name__
        with contextlib.suppress(Exception):
            await h.terminate("fim do teste")  # a cadeia de runs não pode sobreviver ao teste
    return diag, inc, fim


async def test_banda_violada_abre_um_incidente_com_evidencia_e_a_mesma_violacao_nao_duplica(
    env: WorkflowEnvironment,
):
    diag, inc, _ = await rodar(env, Metricas({"lat"}))
    assert [b for b, _ in diag.chamadas] == ["lat"]  # 3 verificações, 1 incidente (mesma janela)
    ((titulo, corpo, _),) = inc.abertos
    assert "banda lat" in titulo and "forja:intent" in corpo and "pico" in corpo
    assert diag.chamadas[0][1] == ["abc123 2026-11-22 feat: x"]


async def test_sem_violacao_nao_abre_nada_e_consulta_cada_banda(env: WorkflowEnvironment):
    m = Metricas(set())
    diag, inc, _ = await rodar(env, m, iteracoes=2)
    assert diag.chamadas == [] and inc.abertos == [] and {"q-lat", "q-dlq"} <= set(m.consultas)


async def verificar(metricas, bandas=None):
    ativ = AtividadesDeOperacao(bandas or FonteDeBandas(), metricas, Diagnostico(), Incidentes())
    return await ActivityEnvironment().run(ativ.checar_bandas, "acme/loja")


def _agora_serie(valores, passo=60):
    agora = time.time()
    n = len(valores)
    return [Amostra(agora - (n - 1 - i) * passo, v) for i, v in enumerate(valores)]


@pytest.mark.parametrize(
    "metricas",
    [
        Metricas(set(), serie_fixa=[]),  # série vazia
        Metricas(set(), serie_fixa=_agora_serie([0.01] * 10 + [float("nan")])),  # NaN
        Metricas(set(), serie_fixa=_agora_serie([0.01] * 3)),  # não cobre a janela
        Metricas(set(), falhar=RuntimeError("prometheus fora")),  # erro de consulta
        Metricas(set(), falhar=PrometheusIndisponivel("avisos")),  # resposta parcial/warning
    ],
    ids=["vazia", "nan", "curta", "erro", "prometheus_indisponivel"],
)
async def test_sem_dado_confiavel_e_sem_dados_nunca_dentro_nem_violada(metricas) -> None:
    resultados = await verificar(metricas)
    assert {r.estado for r in resultados} == {"sem_dados"} and all(r.motivo for r in resultados)


async def test_bandas_do_operador_ilegiveis_sao_ditas_e_nao_somem() -> None:
    class Ruim(FonteDeBandas):
        async def bandas(self, repositorio):
            raise BandasInvalidas("campo desconhecido")

    (r,) = await verificar(Metricas(set()), Ruim())
    assert (r.banda_id, r.estado) == ("*", "sem_dados") and "ilegíveis" in r.motivo


async def test_so_uma_banda_violada_abre_incidente() -> None:
    ativ = AtividadesDeOperacao(FonteDeBandas(), Metricas(set()), Diagnostico(), Incidentes())
    dentro = VerificacaoDto("lat", "dentro")
    sem = VerificacaoDto("lat", "sem_dados", "série vazia")
    for v in (dentro, sem):
        with pytest.raises(ValueError, match="violada"):
            await ActivityEnvironment().run(
                ativ.diagnosticar_e_abrir, IncidenteEntrada("acme/loja", v)
            )


async def test_monitor_sem_dados_nao_abre_nada_nao_falha_e_diz_o_que_nao_viu(env) -> None:
    diag, inc, fim = await rodar(
        env, Metricas(set(), falhar=RuntimeError("prometheus fora")), iteracoes=1
    )
    assert diag.chamadas == [] and inc.abertos == []
    assert fim == "WorkflowContinuedAsNewError"  # seguiu monitorando; não falhou nem "recuperou"


async def test_sem_bands_yaml_nao_ha_o_que_monitorar(env: WorkflowEnvironment):
    class Sem(FonteDeBandas):
        async def bandas(self, repositorio):
            return None

    _, inc, _ = await rodar(env, Metricas({"lat"}), bandas=Sem(), iteracoes=1)
    assert inc.abertos == []


def test_id_do_incidente_e_deterministico_por_repositorio_banda_e_janela() -> None:
    a = id_do_incidente("acme/loja", "lat", 1_000_000.0)
    assert a == id_do_incidente("acme/loja", "lat", 1_000_000.0 + 100)
    assert a != id_do_incidente("acme/loja", "lat", 1_000_000.0 + 7200)
    assert a != id_do_incidente("acme/loja", "dlq", 1_000_000.0)
    assert a != id_do_incidente("acme/outro", "lat", 1_000_000.0)


_ = Client


async def test_o_worker_de_producao_registra_o_monitor_e_iniciar_monitores_e_idempotente(
    env: WorkflowEnvironment,
) -> None:
    import asyncio

    from forja.infrastructure.temporal.activities import DeliveryActivities
    from forja.infrastructure.temporal.worker import (
        criar_worker,
        id_do_monitor,
        iniciar_monitores,
    )
    from tests.infrastructure.temporal.fakes import ExecutorFalso

    diag, inc = Diagnostico(), Incidentes()
    fila = f"prod-{time.time_ns()}"
    op = AtividadesDeOperacao(FonteDeBandas(), Metricas({"lat"}), diag, inc)
    async with criar_worker(env.client, DeliveryActivities(ExecutorFalso()), fila, operacao=op):
        ids = await iniciar_monitores(env.client, ["acme/loja"], 300, fila)
        assert await iniciar_monitores(env.client, ["acme/loja"], 300, fila) == ids  # idempotente
        assert ids == [id_do_monitor("acme/loja")]
        async with asyncio.timeout(20):
            while not inc.abertos:
                await asyncio.sleep(0.05)
        with pytest.raises(ValueError, match="inválido"):
            await iniciar_monitores(env.client, ["../x"], 300, fila)
        await env.client.get_workflow_handle(ids[0]).terminate("fim do teste")
    assert len(inc.abertos) == 1
