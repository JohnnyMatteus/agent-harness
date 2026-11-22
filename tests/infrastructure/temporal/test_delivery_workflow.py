# pyright: basic
import asyncio
import uuid
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


@pytest_asyncio.fixture
async def env():
    # Um servidor por teste: workflows esquecidos ou um lock de time-skipping desbalanceado num
    # teste travavam os seguintes.
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
        await _confirmar(h1, "ana")
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
        await _confirmar(h)
        await h.result()
    assert ex.etapas("c1") == ["plan", "design", "build"]
    # cada etapa vê os artefatos anteriores, como dado
    assert [e for e in ex.entradas if e.intent_id == "c1"][2].artefatos == {
        "intent.md": "# intent\n",
        "spec.md": "# spec\n",
    }


async def test_spec_com_pontos_em_aberto_espera_aprovacao_humana(env):
    pub = PublicadorFalso()
    async with criar_worker(env.client, atividades(2, pub)):
        h, _ = await iniciar_ou_sinalizar(env.client, DeliveryEntrada(intent_id=ID, **REPO))
        await h.signal(DeliveryWorkflow.aprovar, "ana")  # antes do portão: descartada
        await _confirmar(h, "ana")
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
        await _confirmar(h)
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
        await _confirmar(h)
        await _esperar_portao(h, "spec")
        await h.signal(DeliveryWorkflow.aprovar, "ana")
        await h.result()
    assert [e for e in ex.entradas if e.intent_id == ID][-1].artefatos[
        "spec.md"
    ] == "# spec editada\n"


async def _confirmar(h, quem: str = "") -> None:
    await _esperar_portao(h, "intent")
    await h.signal(DeliveryWorkflow.confirmar, quem)


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
        await _confirmar(h)
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
        await _confirmar(h)
        saida = await h.result()
    assert saida.lembretes == 1
    assert f"{ID}:lembrete-1" in [c[0] for c in pub.comentarios]


async def test_gateway_inicia_repete_e_sinaliza(env):
    from forja.application.comandos import Aprovar, Confirmar, CriarIntent, OrigemExterna, Rejeitar
    from forja.domain.intent import Origem, TipoDeOrigem, intent_id_de
    from forja.infrastructure.temporal.worker import TemporalEntregaGateway

    origem = OrigemExterna("dono/repo", 7, "https://x/7")
    gw = TemporalEntregaGateway(env.client)
    cmd = CriarIntent(origem, "titulo", "corpo", "ana")
    async with criar_worker(
        env.client, DeliveryActivities(ExecutorFalso(1), publicador=PublicadorFalso())
    ):
        assert await gw.iniciar(cmd) == "iniciada"
        assert await gw.iniciar(cmd) == "ja_existia"
        h = env.client.get_workflow_handle(
            intent_id_de(Origem(TipoDeOrigem.ISSUE_GITHUB, "dono/repo", "7", "t"))
        )
        await _esperar_portao(h, "intent")
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


async def test_confirmacao_antes_do_resumo_existir_e_descartada(env):
    liberar = asyncio.Event()
    ex = ExecutorFalso(0, liberar)
    async with criar_worker(env.client, DeliveryActivities(ex)):
        h, _ = await iniciar_ou_sinalizar(env.client, DeliveryEntrada(intent_id="a1"))
        await asyncio.sleep(0.3)  # o Intérprete ainda roda: não há intent.md para confirmar
        await h.signal(DeliveryWorkflow.confirmar, "ana")
        liberar.set()
        await _esperar_portao(h, "intent")
        await asyncio.sleep(0.5)
        assert ex.etapas("a1") == ["plan"]  # o sinal antecipado não valeu
        assert await h.query(DeliveryWorkflow.etapa_atual) == "plan"
        await h.signal(DeliveryWorkflow.confirmar, "ana")
        await h.result()
    assert ex.etapas("a1") == ["plan", "design", "build"]


async def test_so_quem_pediu_confirma_o_intent(env):
    ex = ExecutorFalso()
    entrada = DeliveryEntrada(intent_id="a2", solicitantes=["maria", "joao"])
    async with criar_worker(env.client, DeliveryActivities(ex)):
        h, _ = await iniciar_ou_sinalizar(env.client, entrada)
        await _esperar_portao(h, "intent")
        await h.signal(DeliveryWorkflow.confirmar, "intruso")
        await h.signal(DeliveryWorkflow.aprovar, "intruso")  # aprovar não confirma intent
        await asyncio.sleep(0.5)
        assert ex.etapas("a2") == ["plan"]
        await h.signal(DeliveryWorkflow.confirmar, "Maria")
        saida = await h.result()
    assert saida.desfecho == Desfecho.ARTEFATOS_PUBLICADOS


async def test_rejeitar_o_intent_encerra_antes_do_design(env):
    ex = ExecutorFalso()
    async with criar_worker(env.client, DeliveryActivities(ex)):
        h, _ = await iniciar_ou_sinalizar(env.client, DeliveryEntrada(intent_id="a3"))
        await _esperar_portao(h, "intent")
        await h.signal(DeliveryWorkflow.rejeitar, args=["ana", "não é isso"])
        saida = await h.result()
    assert saida.desfecho == Desfecho.REJEITADA and saida.etapas_executadas == ["plan"]


async def test_intent_editado_na_branch_e_o_que_segue_para_o_design(env):
    pub = PublicadorFalso()
    pub.arquivos["intent.md:editado"] = "# intent corrigido\n"
    ex = ExecutorFalso()
    async with criar_worker(env.client, DeliveryActivities(ex, publicador=pub)):
        h, _ = await iniciar_ou_sinalizar(env.client, DeliveryEntrada(intent_id=ID, **REPO))
        await _confirmar(h)
        await h.result()
    assert [e for e in ex.entradas if e.intent_id == ID][1].artefatos[
        "intent.md"
    ] == "# intent corrigido\n"


async def test_falha_ao_ler_a_edicao_humana_nao_segue_com_a_versao_do_modelo(env):
    from temporalio.client import WorkflowFailureError

    pub = PublicadorFalso()
    pub.falha_na_leitura = True
    ex = ExecutorFalso(1)
    async with criar_worker(env.client, DeliveryActivities(ex, publicador=pub)):
        h, _ = await iniciar_ou_sinalizar(env.client, DeliveryEntrada(intent_id=ID, **REPO))
        await _confirmar(h)
        with pytest.raises(WorkflowFailureError):
            await h.result()
    assert ex.etapas(ID) == ["plan"]  # nunca chegou ao design com a spec do modelo


async def test_custo_e_tokens_das_sessoes_chegam_ao_resultado_e_a_metrica(env):
    from forja.infrastructure.telemetry.metricas import MetricasForja

    m = MetricasForja()
    async with criar_worker(env.client, DeliveryActivities(ExecutorFalso(), metricas=m)):
        h, _ = await iniciar_ou_sinalizar(env.client, DeliveryEntrada(intent_id="a4"))
        await _confirmar(h)
        saida = await h.result()
    assert saida.custo_usd == 1.5
    texto = m.exportar().decode()
    assert "forja_custo_usd_total 1.5" in texto
    assert 'forja_tokens_total{direcao="entrada"} 30.0' in texto


async def _rodar_harness(env, harness, pilha=None, aprovar=None, **extra):
    from tests.infrastructure.temporal.fakes import pilha_de_revisao

    pub = PublicadorFalso()
    revisor, leitura, escrita = pilha or pilha_de_revisao()
    ativ = DeliveryActivities(
        ExecutorFalso(),
        publicador=pub,
        harness=harness,
        revisor=revisor,
        leitura=leitura,
        escrita=escrita,
    )
    entrada = DeliveryEntrada(intent_id=ID, harness=True, **{**REPO, **extra})
    # Fila propria: workflows esquecidos por outros testes nao podem roubar as tasks daqui.
    fila = f"forja-harness-{uuid.uuid4().hex}"
    async with criar_worker(env.client, ativ, task_queue=fila):
        h, _ = await iniciar_ou_sinalizar(env.client, entrada, fila)
        await _confirmar(h)
        if aprovar is not None:
            await _esperar_portao(h, "aprovacao")
            if aprovar == "approve":
                await h.signal(DeliveryWorkflow.aprovar, "ana")
            else:
                await h.signal(DeliveryWorkflow.rejeitar, args=["ana", "não vale"])
        return await h.result(), pub, escrita


async def test_harness_ate_o_auto_merge_de_risco_baixo_com_checks_verdes(env):
    from tests.infrastructure.temporal.fakes import HarnessFalso, LeituraFalsa, pilha_de_revisao

    harness = HarnessFalso(blocos=[(("f1",), False), (("f2",), True)])
    pilha = pilha_de_revisao(LeituraFalsa(checks=("pendente", "verde")))
    saida, pub, escrita = await _rodar_harness(env, harness, pilha, automerge=True)
    assert saida.desfecho == Desfecho.MESCLADA and saida.etapa_final == "maintain"
    assert harness.chamadas == ["inicializar", "bloco1", "bloco2", "verificar"]
    assert saida.custo_usd == pytest.approx(1.5 + 0.1 + 0.4 + 0.04)  # + 4 revisores
    assert len(pub.prs) == 1 and "passaram na verificação" in pub.prs[0][1]
    assert [n for n, _ in escrita.checks] == ["seguranca", "testes", "adrs", "desempenho"]
    assert escrita.merges == [7] and escrita.prontos == [7]
    assert "review.md" in [c[0] for c in pub.commits]
    chaves = [c[0] for c in pub.comentarios]
    assert f"{ID}:bloco-1" in chaves and f"{ID}:bloco-2" in chaves and f"{ID}:mesclada" in chaves


async def test_risco_baixo_sem_auto_merge_habilitado_vai_para_o_humano_e_aprova(env):
    from tests.infrastructure.temporal.fakes import HarnessFalso

    saida, _, escrita = await _rodar_harness(
        env, HarnessFalso(), aprovar="approve", automerge=False
    )
    assert saida.desfecho == Desfecho.APROVADA and saida.etapa_final == "deploy"
    assert escrita.merges == [] and escrita.prontos == [7]  # o merge é humano


async def test_risco_medio_ou_alto_nunca_mescla_sozinho_mesmo_com_auto_merge(env):
    from tests.infrastructure.temporal.fakes import HarnessFalso, LeituraFalsa, pilha_de_revisao

    for caminhos in (("src/x.py",), ("docs/a.md", "infra/k8s.yaml")):
        pilha = pilha_de_revisao(LeituraFalsa(caminhos=caminhos))
        saida, _, escrita = await _rodar_harness(
            env, HarnessFalso(), pilha, aprovar="approve", automerge=True
        )
        assert saida.desfecho == Desfecho.APROVADA and escrita.merges == [], caminhos


async def test_sem_politica_declarada_toda_entrega_passa_por_um_humano(env):
    from forja.domain.politica import Politica
    from tests.infrastructure.temporal.fakes import HarnessFalso, LeituraFalsa, pilha_de_revisao

    pilha = pilha_de_revisao(LeituraFalsa(politica=Politica.padrao_fechado()))
    saida, _, escrita = await _rodar_harness(
        env, HarnessFalso(), pilha, aprovar="approve", automerge=True
    )
    assert saida.desfecho == Desfecho.APROVADA and escrita.merges == []


async def test_humano_rejeita_o_pr_e_a_entrega_encerra(env):
    from tests.infrastructure.temporal.fakes import HarnessFalso

    saida, pub, escrita = await _rodar_harness(env, HarnessFalso(), aprovar="reject")
    assert saida.desfecho == Desfecho.REJEITADA and saida.etapa_final == "aguardando_humano"
    assert escrita.prontos == [] and escrita.merges == []
    assert any("pr rejeitada por ana" in c[1] for c in pub.comentarios)


async def test_achado_bloqueante_volta_a_entrega_ao_build_e_falha_para_um_humano(env):
    from forja.domain.politica import Tier
    from forja.domain.revisao import Achado, Severidade
    from tests.infrastructure.temporal.fakes import HarnessFalso, pilha_de_revisao

    achado = Achado("seguranca", Severidade.BLOQUEANTE, "segredo no diff", "src/a.py", 3, Tier.ALTO)
    pilha = pilha_de_revisao(achados_por_revisor={"seguranca": [achado]})
    saida, _, escrita = await _rodar_harness(env, HarnessFalso(), pilha, automerge=True)
    assert saida.desfecho == Desfecho.FALHOU and saida.etapa_final == "build"  # Review -> Build
    assert "segredo no diff" in saida.motivo_da_rejeicao and escrita.merges == []
    assert ("seguranca", "failure") in escrita.checks and ("testes", "success") in escrita.checks


async def test_checks_do_pr_que_falham_ou_nao_terminam_impedem_o_merge(env):
    from tests.infrastructure.temporal.fakes import HarnessFalso, LeituraFalsa, pilha_de_revisao

    falhou = pilha_de_revisao(LeituraFalsa(checks=("falhou",)))
    saida, _, escrita = await _rodar_harness(env, HarnessFalso(), falhou, automerge=True)
    assert saida.desfecho == Desfecho.FALHOU and "falharam" in saida.motivo_da_rejeicao
    pendente = pilha_de_revisao(LeituraFalsa(checks=("pendente",)))
    # Sem confirmação a tempo, não há auto-merge: a decisão vai para um humano (aqui, rejeita).
    saida, pub, escrita = await _rodar_harness(
        env,
        HarnessFalso(),
        pendente,
        aprovar="reject",
        automerge=True,
        max_esperas_dos_checks=2,
        espera_dos_checks_s=0.05,  # relogio real: o portao e esperado por polling
    )
    assert saida.desfecho == Desfecho.REJEITADA and saida.etapa_final == "aguardando_humano"
    assert escrita.merges == [] and escrita.prontos == []
    assert any("Um humano decide" in c[1] for c in pub.comentarios)


async def test_orcamento_por_intencao_e_por_sessoes_interrompe_a_entrega(env):
    from forja.domain.politica import Politica
    from tests.infrastructure.temporal.fakes import HarnessFalso, LeituraFalsa, pilha_de_revisao

    caro = Politica.de_dict({"budgets": {"per_intent_usd": 1.0}})  # as etapas já gastaram 1,5
    harness = HarnessFalso()
    saida, _, _ = await _rodar_harness(env, harness, pilha_de_revisao(LeituraFalsa(politica=caro)))
    assert saida.desfecho == Desfecho.FALHOU and "orçamento" in saida.motivo_da_rejeicao
    assert harness.chamadas == ["inicializar"]  # nenhum bloco pago depois do teto
    poucas = Politica.de_dict({"budgets": {"max_sessions_per_intent": 1, "per_intent_usd": 100}})
    harness = HarnessFalso(blocos=[(("f1",), False), (("f2",), True)])
    saida, _, _ = await _rodar_harness(
        env, harness, pilha_de_revisao(LeituraFalsa(politica=poucas))
    )
    assert saida.desfecho == Desfecho.FALHOU and "sessões" in saida.motivo_da_rejeicao
    assert harness.chamadas == ["inicializar", "bloco1"]


async def test_harness_sem_progresso_devolve_o_feedback_e_depois_falha_para_um_humano(env):
    from tests.infrastructure.temporal.fakes import HarnessFalso

    harness = HarnessFalso(blocos=[((), False)] * 5)
    saida, pub, _ = await _rodar_harness(env, harness, rodadas_sem_progresso=2)
    assert (
        saida.desfecho == Desfecho.FALHOU
        and "sem funcionalidade aprovada" in saida.motivo_da_rejeicao
    )
    assert harness.feedbacks == [
        "",
        "teste sem passar: f1",
    ]  # o feedback do bloco volta ao seguinte
    assert pub.prs == []


async def test_verificacao_final_vermelha_conta_ciclo_e_falha(env):
    from tests.infrastructure.temporal.fakes import HarnessFalso

    harness = HarnessFalso(verde=False)
    saida, pub, _ = await _rodar_harness(env, harness)
    assert saida.desfecho == Desfecho.FALHOU and saida.etapa_final == "build"  # Test -> Build
    assert "f1" in saida.motivo_da_rejeicao and pub.prs == []


async def test_harness_desligado_mantem_o_comportamento_do_m3(env):
    pub = PublicadorFalso()
    async with criar_worker(env.client, DeliveryActivities(ExecutorFalso(), publicador=pub)):
        h, _ = await iniciar_ou_sinalizar(env.client, DeliveryEntrada(intent_id=ID, **REPO))
        await _confirmar(h)
        saida = await h.result()
    assert saida.desfecho == Desfecho.ARTEFATOS_PUBLICADOS and "ainda não foi" in pub.prs[0][1]


async def test_parar_cancela_o_bloco_em_curso(env):
    from tests.infrastructure.temporal.fakes import HarnessFalso, pilha_de_revisao

    harness = HarnessFalso(atraso=3600)
    pub = PublicadorFalso()
    revisor, leitura, escrita = pilha_de_revisao()
    ativ = DeliveryActivities(
        ExecutorFalso(),
        publicador=pub,
        harness=harness,
        revisor=revisor,
        leitura=leitura,
        escrita=escrita,
        intervalo_heartbeat_s=0.2,
    )
    async with criar_worker(env.client, ativ):
        h, _ = await iniciar_ou_sinalizar(
            env.client, DeliveryEntrada(intent_id=ID, harness=True, heartbeat_s=2, **REPO)
        )
        await _confirmar(h)
        async with asyncio.timeout(30):
            while "bloco1" not in harness.chamadas:
                await asyncio.sleep(0.05)
        await h.signal(DeliveryWorkflow.parar)
        await asyncio.sleep(1)
        saida = await h.result()
    assert saida.desfecho == Desfecho.CANCELADA and pub.prs == []


async def test_branch_que_andou_alem_do_review_invalida_a_revisao_antes_dos_checks(env):
    from forja.domain.revisao import AvancoDaBranch
    from tests.infrastructure.temporal.fakes import HarnessFalso, LeituraFalsa, pilha_de_revisao

    review = ".forja/0123456789abcdef/review.md"
    for avanco in (
        AvancoDaBranch(1, ("src/evil.py",)),
        AvancoDaBranch(1, (review, "src/evil.py")),
        AvancoDaBranch(2, (review,)),
    ):
        leitura = LeituraFalsa()
        leitura.avanco_fixo = avanco
        saida, _, escrita = await _rodar_harness(
            env, HarnessFalso(), pilha_de_revisao(leitura), automerge=True
        )
        assert (
            saida.desfecho == Desfecho.FALHOU
            and "mudou depois da revisão" in saida.motivo_da_rejeicao
        )
        assert escrita.checks == [] and escrita.merges == [] and escrita.prontos == []


async def test_branch_que_anda_entre_a_revisao_e_o_merge_nao_mescla(env):
    from tests.infrastructure.temporal.fakes import HarnessFalso, LeituraFalsa, pilha_de_revisao

    leitura = LeituraFalsa()
    leitura.pontas = ["b" * 40, "c" * 40]  # a ponta pós-review e, depois, outra
    saida, _, escrita = await _rodar_harness(
        env, HarnessFalso(), pilha_de_revisao(leitura), automerge=True
    )
    assert saida.desfecho == Desfecho.FALHOU and "andou" in saida.motivo_da_rejeicao
    assert escrita.merges == [] and escrita.prontos == []


async def test_aprovacao_humana_vale_so_para_o_sha_revisado(env):
    from tests.infrastructure.temporal.fakes import HarnessFalso, LeituraFalsa, pilha_de_revisao

    leitura = LeituraFalsa()
    leitura.pontas = ["b" * 40, "c" * 40]
    saida, _, escrita = await _rodar_harness(
        env, HarnessFalso(), pilha_de_revisao(leitura), aprovar="approve", automerge=False
    )
    assert (
        saida.desfecho == Desfecho.FALHOU
        and "aprovação valia só para o SHA" in saida.motivo_da_rejeicao
    )
    assert escrita.prontos == []


async def test_sem_check_externo_verde_nao_ha_auto_merge_mesmo_com_tudo_permitindo(env):
    from tests.infrastructure.temporal.fakes import HarnessFalso, LeituraFalsa, pilha_de_revisao

    pilha = pilha_de_revisao(LeituraFalsa(checks=("sem_externos",)))
    saida, _, escrita = await _rodar_harness(
        env, HarnessFalso(), pilha, aprovar="approve", automerge=True
    )
    assert saida.desfecho == Desfecho.APROVADA and escrita.merges == []


async def test_checks_que_deixam_de_ser_verdes_no_momento_do_merge_nao_mesclam(env):
    from tests.infrastructure.temporal.fakes import HarnessFalso, LeituraFalsa, pilha_de_revisao

    pilha = pilha_de_revisao(LeituraFalsa(checks=("verde", "falhou")))
    saida, _, escrita = await _rodar_harness(env, HarnessFalso(), pilha, automerge=True)
    assert saida.desfecho == Desfecho.FALHOU and "checks_mudaram" in saida.motivo_da_rejeicao
    assert escrita.merges == []


async def test_harness_sem_leitura_de_politica_falha_em_vez_de_assumir_orcamento_ilimitado(env):
    from temporalio.client import WorkflowFailureError

    from tests.infrastructure.temporal.fakes import HarnessFalso

    ativ = DeliveryActivities(
        ExecutorFalso(), publicador=PublicadorFalso(), harness=HarnessFalso(), leitura=None
    )
    async with criar_worker(env.client, ativ):
        h, _ = await iniciar_ou_sinalizar(
            env.client, DeliveryEntrada(intent_id=ID, harness=True, **REPO)
        )
        await _confirmar(h)
        with pytest.raises(WorkflowFailureError):
            await h.result()
