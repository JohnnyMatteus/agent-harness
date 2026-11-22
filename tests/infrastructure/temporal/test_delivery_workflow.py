# pyright: basic
import asyncio
from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
from temporalio.client import WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment

from forja.infrastructure.temporal.activities import DeliveryActivities, EtapaEntrada, EtapaSaida
from forja.infrastructure.temporal.worker import criar_worker, iniciar_ou_sinalizar
from forja.infrastructure.temporal.workflows import DeliveryEntrada, DeliveryWorkflow, Desfecho
from tests.infrastructure.temporal.fakes import ExecutorFalso, PublicadorFalso

pytestmark = pytest.mark.asyncio(loop_scope="module")
ID = "0123456789abcdef"
REPO: dict[str, Any] = {
    "repositorio": "acme/loja",
    "numero": 7,
    "titulo": "Corrigir login",
    "slug": "corrigir-login",
}


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def env():
    async with await WorkflowEnvironment.start_time_skipping() as e:
        yield e


def atividades(pontos: int = 0, publicador: PublicadorFalso | None = None):
    return DeliveryActivities(ExecutorFalso(pontos), publicador=publicador)


async def test_um_workflow_por_intencao_e_ate_o_pr(env):
    pub = PublicadorFalso()
    entrada = DeliveryEntrada(intent_id=ID, **REPO)
    async with criar_worker(env.client, atividades(0, pub)):
        h1, novo1 = await iniciar_ou_sinalizar(env.client, entrada)
        h2, novo2 = await iniciar_ou_sinalizar(env.client, entrada)
        assert (novo1, novo2) == (True, False) and h1.id == h2.id == ID
        await h1.signal(DeliveryWorkflow.confirmar, "ana")
        saida = await h1.result()
    assert saida.sinais_repetidos == 1
    assert saida.desfecho == Desfecho.ARTEFATOS_PUBLICADOS
    assert saida.etapas_executadas == ["plan", "design", "build"]
    assert [c[0] for c in pub.commits] == ["intent.md", "spec.md", "plan.md"]
    assert saida.pr_url == "https://github.test/pr/1" and len(pub.prs) == 1
    assert "Intent-Id: " + ID in pub.commits[0][1]


async def test_nada_avanca_antes_da_confirmacao(env):
    ex = ExecutorFalso()
    async with criar_worker(env.client, DeliveryActivities(ex)):
        h, _ = await iniciar_ou_sinalizar(env.client, DeliveryEntrada(intent_id="c1"))
        await asyncio.sleep(0.3)
        assert await h.query(DeliveryWorkflow.etapa_atual) == "plan"
        assert [e.etapa for e in ex.entradas] == ["plan"]
        await h.signal(DeliveryWorkflow.confirmar)
        await h.result()
    assert [e.etapa for e in ex.entradas] == ["plan", "design", "build"]
    # cada etapa vê os artefatos anteriores, como dado
    assert ex.entradas[2].artefatos == {"intent.md": "# intent\n", "spec.md": "# spec\n"}


async def test_spec_com_pontos_em_aberto_espera_aprovacao_humana(env):
    pub = PublicadorFalso()
    async with criar_worker(env.client, atividades(2, pub)):
        h, _ = await iniciar_ou_sinalizar(env.client, DeliveryEntrada(intent_id=ID, **REPO))
        await h.signal(DeliveryWorkflow.aprovar, "ana")  # antes do portão: descartada
        await h.signal(DeliveryWorkflow.confirmar, "ana")
        await _esperar_portao(h, "spec")
        assert await h.query(DeliveryWorkflow.etapa_atual) == "aguardando_spec"
        assert not any(c[0] == "plan.md" for c in pub.commits)
        await h.signal(DeliveryWorkflow.aprovar, "ana")
        saida = await h.result()
    assert saida.desfecho == Desfecho.ARTEFATOS_PUBLICADOS
    assert saida.etapas_executadas == ["plan", "design", "build"]


async def test_rejeicao_encerra_sem_build_e_sem_pr(env):
    pub = PublicadorFalso()
    async with criar_worker(env.client, atividades(1, pub)):
        h, _ = await iniciar_ou_sinalizar(env.client, DeliveryEntrada(intent_id=ID, **REPO))
        await h.signal(DeliveryWorkflow.confirmar)
        await _esperar_portao(h, "spec")
        await h.signal(DeliveryWorkflow.rejeitar, args=["bia", "fora do escopo " + "x" * 900])
        saida = await h.result()
    assert saida.desfecho == Desfecho.REJEITADA and saida.etapa_final == "aguardando_spec"
    assert saida.etapas_executadas == ["plan", "design"] and len(saida.motivo_da_rejeicao) == 500
    assert pub.prs == [] and "plan.md" not in [c[0] for c in pub.commits]
    assert any("rejeitada por bia" in c[1] for c in pub.comentarios)


async def test_spec_editada_pelo_humano_vai_para_o_planner(env):
    pub = PublicadorFalso()
    pub.arquivos["spec.md:editado"] = "# spec editada\n"
    ex = ExecutorFalso(1)
    async with criar_worker(env.client, DeliveryActivities(ex, publicador=pub)):
        h, _ = await iniciar_ou_sinalizar(env.client, DeliveryEntrada(intent_id=ID, **REPO))
        await h.signal(DeliveryWorkflow.confirmar)
        await _esperar_portao(h, "spec")
        await h.signal(DeliveryWorkflow.aprovar, "ana")
        await h.result()
    assert ex.entradas[-1].artefatos["spec.md"] == "# spec editada\n"


async def _esperar_portao(h, nome: str) -> None:
    async with asyncio.timeout(30):
        while await h.query(DeliveryWorkflow.portao_aberto) != nome:
            await asyncio.sleep(0.05)


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
        await asyncio.wait_for(iniciou.wait(), 30)
        await h.signal(DeliveryWorkflow.parar)
        # O cancelamento chega pelo heartbeat (throttle do SDK); aguardar antes de result()
        # evita que o time-skipping estoure o heartbeat_timeout.
        await asyncio.wait_for(cancelada.wait(), 30)
        saida = await h.result()
    assert saida.desfecho == Desfecho.CANCELADA


async def test_sobrevive_a_reinicio_do_worker(env):
    async with criar_worker(env.client, atividades(), max_cached_workflows=0):
        h, _ = await iniciar_ou_sinalizar(env.client, DeliveryEntrada(intent_id="r1"))
        await asyncio.sleep(0.3)
    assert (await h.describe()).status == WorkflowExecutionStatus.RUNNING
    async with criar_worker(env.client, atividades(), max_cached_workflows=0):
        await h.signal(DeliveryWorkflow.confirmar)
        saida = await h.result()
    assert saida.desfecho == Desfecho.ARTEFATOS_PUBLICADOS


async def test_timer_publica_lembrete_idempotente_por_numero(env):
    prazo = 48 * 3600
    pub = PublicadorFalso()
    async with criar_worker(env.client, atividades(0, pub)):
        h, _ = await iniciar_ou_sinalizar(
            env.client, DeliveryEntrada(intent_id=ID, prazo_lembrete_s=prazo, **REPO)
        )
        await asyncio.sleep(0.5)
        await env.sleep(timedelta(seconds=prazo + 60))
        assert await h.query(DeliveryWorkflow.lembretes_registrados) == 1
        await h.signal(DeliveryWorkflow.confirmar)
        saida = await h.result()
    assert saida.lembretes == 1
    assert f"{ID}:lembrete-1" in [c[0] for c in pub.comentarios]


async def test_gateway_inicia_repete_e_sinaliza(env):
    from forja.application.comandos import Aprovar, Confirmar, CriarIntent, OrigemExterna, Rejeitar
    from forja.infrastructure.temporal.worker import TemporalEntregaGateway

    origem = OrigemExterna("dono/repo", 7, "https://x/7")
    gw = TemporalEntregaGateway(env.client)
    cmd = CriarIntent(origem, "titulo", "corpo", "ana")
    async with criar_worker(env.client, DeliveryActivities(ExecutorFalso(1))):
        assert await gw.iniciar(cmd) == "iniciada"
        assert await gw.iniciar(cmd) == "ja_existia"
        assert await gw.sinalizar(Confirmar(origem, "ana")) is True
        assert await gw.sinalizar(Aprovar(origem, "ana")) is True
        assert await gw.sinalizar(Rejeitar(origem, "ana", "x")) is True
        assert await gw.parar(origem) is True
        outra = OrigemExterna("dono/outro", 1, "u")
        assert await gw.parar(outra) is False
        assert await gw.sinalizar(Confirmar(outra, "ana")) is False


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
