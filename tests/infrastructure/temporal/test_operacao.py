# pyright: basic
"""Maintain: monitor de bandas e IncidentWorkflow com Temporal de teste e dublês."""

import contextlib
import time

import pytest
import pytest_asyncio
from temporalio.client import Client, WorkflowContinuedAsNewError
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import Worker

from forja.application.portas.agente import UsoModelo
from forja.application.portas.sdlc import Resultado
from forja.domain.artefatos import Fonte
from forja.domain.bandas import Amostra, Bandas
from forja.domain.incidente import Incidente
from forja.infrastructure.telemetry.metricas import MetricasForja
from forja.infrastructure.telemetry.prometheus import PrometheusIndisponivel
from forja.infrastructure.temporal.operacao import (
    AberturaEntrada,
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


REPOS = frozenset({"acme/loja"})


class Metricas:
    def __init__(self, violadas: set[str], falhar: Exception | None = None, serie_fixa=None):
        self.violadas, self.falhar, self.serie_fixa = violadas, falhar, serie_fixa
        self.consultas: list[str] = []
        self.fins: list[float] = []

    async def serie(self, consulta, janela_s, passo_s, fim):
        self.consultas.append(consulta)
        self.fins.append(fim)
        if self.falhar:
            raise self.falhar
        if self.serie_fixa is not None:
            return self.serie_fixa
        valor = 0.9 if consulta.removeprefix("q-") in self.violadas else 0.01
        return [Amostra(fim - (10 - i) * passo_s, valor) for i in range(11)]


class Diagnostico:
    def __init__(self, falhar: Exception | None = None):
        self.chamadas = []
        self.falhar = falhar

    async def diagnosticar(self, repositorio, banda, evidencia, deploys):
        self.chamadas.append((banda.id, deploys))
        if self.falhar:
            raise self.falhar
        return Resultado(
            Incidente(
                evidencia,
                "causa provável: deploy",
                "reverter",
                ("pico 0.9",),
                (Fonte("i", "docs/runbook.md", "c" * 40),),
            ),
            UsoModelo(100, 50, 0.25),
        )


class Incidentes:
    def __init__(self, falhar: Exception | None = None):
        self.abertos = []
        self.tentativas = 0
        self.falhar = falhar

    async def abrir(self, repositorio, titulo, corpo, chave):
        self.tentativas += 1
        if self.falhar:
            raise self.falhar
        self.abertos.append((titulo, corpo, chave))
        return "https://github.test/issues/9"


def atividades(metricas, bandas=None, diag=None, inc=None, repos=REPOS, telemetria=None):
    return AtividadesDeOperacao(
        bandas or FonteDeBandas(),
        metricas,
        diag or Diagnostico(),
        inc or Incidentes(),
        repos,
        passo_s=60,
        telemetria=telemetria,
    )


async def rodar(env, metricas, bandas=None, iteracoes=3, diag=None, inc=None, repos=REPOS,
                telemetria=None, registrar=True, intervalo=300):  # fmt: skip
    diag, inc = diag or Diagnostico(), inc or Incidentes()
    fila = f"op-{time.time_ns()}"  # cada teste a sua fila: o monitor continua-como-novo sem parar
    ativ = atividades(metricas, bandas, diag, inc, repos, telemetria)
    async with Worker(
        env.client, task_queue=fila, workflows=[MonitorDeBandas, IncidentWorkflow],
        activities=(
            [ativ.checar_bandas, ativ.diagnosticar, ativ.abrir_incidente] if registrar else []
        ),
    ):  # fmt: skip
        h = await env.client.start_workflow(
            MonitorDeBandas.run, MonitorEntrada("acme/loja", intervalo, iteracoes),
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


async def verificar(metricas, bandas=None, repos=REPOS):
    return await ActivityEnvironment().run(
        atividades(metricas, bandas, repos=repos).checar_bandas, "acme/loja"
    )


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


async def test_a_consulta_e_a_avaliacao_usam_o_mesmo_instante_end() -> None:
    m = Metricas(set())
    await verificar(m)
    assert len(m.fins) == 2 and all(f > 1e9 for f in m.fins)  # cada banda, o seu `fim`


@pytest.mark.parametrize(
    "bandas",
    [
        None,  # arquivo ausente ou symlink (o adaptador devolve None)
        Bandas.de_dict({"service": "s", "bands": []}),  # `bands: []`
    ],
    ids=["ausente", "lista_vazia"],
)
async def test_repositorio_monitorado_sem_bandas_nao_parece_saudavel(bandas) -> None:
    class Fonte(FonteDeBandas):
        async def bandas(self, repositorio):
            return bandas

    (r,) = await verificar(Metricas(set()), Fonte())
    assert (r.banda_id, r.estado) == ("*", "sem_dados") and "não configuradas" in r.motivo


@pytest.mark.parametrize(
    "conteudo",
    [b"service: [\n  x: : :\n", b"service: \xff\xfe\n", b"service: s\nbands: []\nextra: 1\n"],
    ids=["yaml_quebrado", "nao_utf8", "campo_desconhecido"],
)
async def test_arquivo_de_bandas_ilegivel_vira_sem_dados_e_nao_levanta(tmp_path, conteudo) -> None:
    from forja.infrastructure.telemetry.bandas_do_operador import BandasDoOperador

    (tmp_path / "acme__loja.yaml").write_bytes(conteudo)

    class Fonte(FonteDeBandas):
        async def bandas(self, repositorio):
            return await BandasDoOperador(tmp_path).bandas(repositorio)

    (r,) = await verificar(Metricas(set()), Fonte())
    assert (r.banda_id, r.estado) == ("*", "sem_dados") and "ilegíveis" in r.motivo


async def test_erro_de_leitura_das_bandas_tambem_vira_sem_dados() -> None:
    class Fonte(FonteDeBandas):
        async def bandas(self, repositorio):
            raise OSError("disco")

    (r,) = await verificar(Metricas(set()), Fonte())
    assert r.estado == "sem_dados" and "OSError" in r.motivo


async def test_so_uma_banda_violada_abre_incidente() -> None:
    ativ = atividades(Metricas(set()))
    dentro = VerificacaoDto("lat", "dentro")
    sem = VerificacaoDto("lat", "sem_dados", "série vazia")
    for v in (dentro, sem):
        with pytest.raises(ValueError, match="violada"):
            await ActivityEnvironment().run(ativ.diagnosticar, IncidenteEntrada("acme/loja", v))


async def test_monitor_com_prometheus_fora_nao_abre_nada_nao_falha_e_conta_sem_dados(env) -> None:
    tel = MetricasForja()
    diag, inc, fim = await rodar(
        env, Metricas(set(), falhar=RuntimeError("prometheus fora")), iteracoes=1, telemetria=tel
    )
    assert diag.chamadas == [] and inc.abertos == []
    assert fim == "WorkflowContinuedAsNewError"  # seguiu monitorando; não falhou nem "recuperou"
    # duas bandas por verificação; o run seguinte (continue-as-new) pode ter verificado também
    assert (tel.registry.get_sample_value("forja_bandas_sem_dados_total") or 0) >= 2


async def test_o_monitor_nunca_morre_por_falha_de_activity(env: WorkflowEnvironment) -> None:
    """Activity que falha (aqui, `checar_bandas` levantando em todas as tentativas): o monitor
    registra `sem_dados`, espera e segue até o continue-as-new. (Activity não registrada ou com
    timeout cai no mesmo `except ActivityError`, mas o servidor de time-skipping não dispara o
    timeout de uma activity que ninguém pegou, então essa variante não é exercitada aqui.)"""
    from temporalio import activity

    chamadas = []

    @activity.defn(name="checar_bandas")
    async def quebrada(repositorio: str) -> list[VerificacaoDto]:
        chamadas.append(repositorio)
        raise RuntimeError("bug na activity")

    fila = f"op-{time.time_ns()}"
    async with Worker(
        env.client, task_queue=fila, workflows=[MonitorDeBandas, IncidentWorkflow],
        activities=[quebrada],
    ):  # fmt: skip
        h = await env.client.start_workflow(
            MonitorDeBandas.run, MonitorEntrada("acme/loja", 300, 2),
            id=f"mon-{time.time_ns()}", task_queue=fila,
        )  # fmt: skip
        with pytest.raises(WorkflowContinuedAsNewError):  # chegou ao fim sem morrer
            await h.result(follow_runs=False)
        with contextlib.suppress(Exception):
            await h.terminate("fim do teste")
    assert len(chamadas) >= 6  # 2 iterações, 3 tentativas cada: falhou, registrou e seguiu


async def test_uma_tentativa_paga_por_janela_mesmo_se_o_diagnostico_falha(env) -> None:
    diag = Diagnostico(falhar=RuntimeError("modelo caiu depois de gastar"))
    _, inc, _ = await rodar(env, Metricas({"lat"}), iteracoes=4, diag=diag)
    assert len(diag.chamadas) == 1 and inc.abertos == []  # nem 3 retentativas nem 1 por intervalo


async def test_falhar_ao_abrir_a_issue_nao_paga_o_diagnostico_de_novo_e_o_custo_e_medido(
    env,
) -> None:
    tel = MetricasForja()
    inc = Incidentes(falhar=RuntimeError("github fora"))
    diag, _, _ = await rodar(env, Metricas({"lat"}), iteracoes=3, inc=inc, telemetria=tel)
    assert len(diag.chamadas) == 1 and inc.tentativas > 1  # a issue é retentada; o LLM, não
    leitura = tel.registry.get_sample_value
    assert leitura("forja_diagnosticos_total") == 1 and leitura("forja_custo_usd_total") == 0.25
    assert leitura("forja_tokens_total", {"direcao": "entrada"}) == 100


async def test_repositorio_fora_da_lista_do_operador_para_o_monitor_e_as_activities_recusam(
    env,
) -> None:
    diag, inc, fim = await rodar(
        env, Metricas({"lat"}), iteracoes=3, repos=frozenset({"acme/outro"})
    )
    assert diag.chamadas == [] and inc.abertos == []
    assert fim == "concluiu"  # o monitor terminou sozinho em vez de seguir abrindo issue
    (r,) = await verificar(Metricas({"lat"}), repos=frozenset())
    assert r.estado == "desativado"
    ativ = atividades(Metricas(set()), repos=frozenset())
    v = VerificacaoDto("lat", "violada", "", "q", 0.3, 300, 0.9, 0.9, 5)
    with pytest.raises(ValueError, match="FORJA_MONITOR_REPOS"):
        await ActivityEnvironment().run(ativ.diagnosticar, IncidenteEntrada("acme/loja", v))
    with pytest.raises(ValueError, match="FORJA_MONITOR_REPOS"):
        await ActivityEnvironment().run(
            ativ.abrir_incidente, AberturaEntrada("acme/loja", "lat", "t", "c")
        )


def test_intervalo_do_monitor_e_finito_e_de_30s_a_24h() -> None:
    from forja.infrastructure.temporal.operacao import intervalo_valido

    assert intervalo_valido(float("nan")) == 30.0 and intervalo_valido(1) == 30.0
    assert intervalo_valido(float("inf")) == 24 * 3600.0 and intervalo_valido(300) == 300


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
    op = atividades(Metricas({"lat"}), diag=diag, inc=inc)
    async with criar_worker(env.client, DeliveryActivities(ExecutorFalso()), fila, operacao=op):
        ids = await iniciar_monitores(env.client, ["acme/loja"], 300, fila)
        assert await iniciar_monitores(env.client, ["acme/loja"], 300, fila) == ids  # idempotente
        assert ids == [id_do_monitor("acme/loja")]
        async with asyncio.timeout(20):
            while not inc.abertos:
                await asyncio.sleep(0.05)
        with pytest.raises(ValueError, match="inválido"):
            await iniciar_monitores(env.client, ["../x"], 300, fila)
        for ruim in (float("nan"), float("inf"), 5):
            with pytest.raises(ValueError, match="intervalo"):
                await iniciar_monitores(env.client, ["acme/loja"], ruim, fila)
        await env.client.get_workflow_handle(ids[0]).terminate("fim do teste")
    assert len(inc.abertos) == 1
