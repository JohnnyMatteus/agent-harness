# pyright: basic
import asyncio
from datetime import timedelta

import pytest
import pytest_asyncio
from temporalio.client import WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment

from forja.infrastructure.temporal.activities import DeliveryActivities, EtapaEntrada, EtapaSaida
from forja.infrastructure.temporal.worker import criar_worker, iniciar_ou_sinalizar
from forja.infrastructure.temporal.workflows import DeliveryEntrada, DeliveryWorkflow, Desfecho

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def env():
    async with await WorkflowEnvironment.start_time_skipping() as e:
        yield e


async def test_um_workflow_por_intencao(env):
    entrada = DeliveryEntrada(intent_id="abc")
    async with criar_worker(env.client):
        h1, novo1 = await iniciar_ou_sinalizar(env.client, entrada)
        h2, novo2 = await iniciar_ou_sinalizar(env.client, entrada)
        assert (novo1, novo2) == (True, False)
        assert h1.id == h2.id == "abc"
        await h1.signal(DeliveryWorkflow.confirmar)
        saida = await h1.result()
    assert saida.sinais_repetidos == 1
    assert saida.desfecho == Desfecho.CONCLUIDA


async def test_confirmar_avanca_de_plan_para_design(env):
    async with criar_worker(env.client):
        h, _ = await iniciar_ou_sinalizar(env.client, DeliveryEntrada(intent_id="c1"))
        assert await h.query(DeliveryWorkflow.etapa_atual) == "plan"
        await h.signal(DeliveryWorkflow.confirmar)
        saida = await h.result()
    assert saida.etapas_executadas[:4] == ["plan", "design", "build", "test"]


async def test_parar_cancela_workflow_e_activity_em_curso(env):
    iniciou, cancelada = asyncio.Event(), asyncio.Event()

    async def executor_lento(entrada: EtapaEntrada) -> EtapaSaida:
        iniciou.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelada.set()
            raise
        return EtapaSaida(etapa=entrada.etapa)

    ativ = DeliveryActivities(executor_lento, intervalo_heartbeat_s=0.2)
    async with criar_worker(env.client, ativ):
        h, _ = await iniciar_ou_sinalizar(
            env.client, DeliveryEntrada(intent_id="p1", heartbeat_s=2)
        )
        await h.signal(DeliveryWorkflow.confirmar)
        await asyncio.wait_for(iniciou.wait(), 30)
        await h.signal(DeliveryWorkflow.parar)
        # O cancelamento chega pelo heartbeat (throttle do SDK); aguardar antes de result()
        # evita que o time-skipping estoure o heartbeat_timeout.
        await asyncio.wait_for(cancelada.wait(), 30)
        saida = await h.result()
    assert saida.desfecho == Desfecho.CANCELADA


async def test_sobrevive_a_reinicio_do_worker(env):
    async with criar_worker(env.client, max_cached_workflows=0):
        h, _ = await iniciar_ou_sinalizar(env.client, DeliveryEntrada(intent_id="r1"))
        assert await h.query(DeliveryWorkflow.etapa_atual) == "plan"
    # sem cache (sem sticky queue) o segundo worker assume o workflow na hora, como após reinício
    # worker parado: o workflow segue aguardando no servidor
    assert (await h.describe()).status == WorkflowExecutionStatus.RUNNING
    async with criar_worker(env.client, max_cached_workflows=0):
        await h.signal(DeliveryWorkflow.confirmar)
        saida = await h.result()
    assert saida.desfecho == Desfecho.CONCLUIDA


async def test_timer_registra_lembrete_sem_enviar_nada(env):
    prazo = 48 * 3600
    async with criar_worker(env.client):
        h, _ = await iniciar_ou_sinalizar(
            env.client, DeliveryEntrada(intent_id="t1", prazo_lembrete_s=prazo)
        )
        await env.sleep(timedelta(seconds=prazo + 60))
        assert await h.query(DeliveryWorkflow.lembretes_registrados) == 1
        await h.signal(DeliveryWorkflow.confirmar)
        saida = await h.result()
    assert saida.lembretes == 1


async def test_gateway_inicia_e_repete_como_sinal(env):
    from forja.application.comandos import CriarIntent, OrigemExterna
    from forja.infrastructure.temporal.worker import TemporalEntregaGateway

    origem = OrigemExterna("dono/repo", 7, "https://x/7")
    gw = TemporalEntregaGateway(env.client)
    cmd = CriarIntent(origem, "titulo", "corpo", "ana")
    async with criar_worker(env.client):
        assert await gw.iniciar(cmd) == "iniciada"
        assert await gw.iniciar(cmd) == "ja_existia"
        assert await gw.parar(origem) is True
        assert (await gw.parar(OrigemExterna("dono/outro", 1, "u"))) is False


async def test_cancelar_todas_sinaliza_cada_workflow_em_execucao():
    from types import SimpleNamespace

    from forja.infrastructure.temporal.worker import TemporalEntregaGateway

    sinalizados: list[str] = []

    class Handle:
        def __init__(self, wid: str) -> None:
            self.wid = wid

        async def signal(self, _sinal):
            sinalizados.append(self.wid)

    class ClienteFalso:
        async def list_workflows(self, _query):
            for wid in ("a", "b"):
                yield SimpleNamespace(id=wid)

        def get_workflow_handle(self, wid):
            return Handle(wid)

    assert await TemporalEntregaGateway(ClienteFalso()).cancelar_todas() == 2  # type: ignore[arg-type]
    assert sinalizados == ["a", "b"]
