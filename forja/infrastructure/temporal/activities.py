"""Activities do DeliveryWorkflow: uma por etapa. Efeitos externos moram aqui."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Protocol

from temporalio import activity
from temporalio.exceptions import ApplicationError

from forja.application.casos_de_uso.revisao import RevisarEntrega
from forja.application.portas.agente import UsoModelo
from forja.application.portas.harness import ContextoDaEntrega, Harness
from forja.application.portas.publicador import DestinoDaEntrega, PublicadorDeEntrega
from forja.application.portas.revisao import EscritaDeRevisao, LeituraDeRevisao
from forja.domain.politica import Tier
from forja.domain.revisao import REVISORES, Achado, Severidade
from forja.infrastructure.github.cliente import nome_da_branch
from forja.infrastructure.telemetry.metricas import MetricasForja


@dataclass(frozen=True)
class EtapaEntrada:
    intent_id: str
    etapa: str
    # Contexto da origem. `titulo` e `corpo` são texto não confiável: só viram dado delimitado.
    repositorio: str = ""
    numero: int = 0
    titulo: str = ""
    corpo: str = ""
    url: str = ""
    # Artefatos já produzidos (intent.md, spec.md...), por nome; também dado, não instrução.
    artefatos: dict[str, str] = field(default_factory=dict[str, str])


@dataclass(frozen=True)
class EtapaSaida:
    etapa: str
    resumo: str = ""
    texto: str = ""
    pontos_em_aberto: int = 0
    tokens_entrada: int = 0
    tokens_saida: int = 0
    custo_usd: float = 0.0


@dataclass(frozen=True)
class PublicarEntrada:
    repositorio: str
    numero: int
    corpo: str
    chave: str


@dataclass(frozen=True)
class ArtefatoEntrada:
    repositorio: str
    intent_id: str
    slug: str
    nome: str
    conteudo: str = ""
    etapa: str = ""


@dataclass(frozen=True)
class HarnessEntrada:
    repositorio: str
    intent_id: str
    slug: str
    bloco: int = 0
    artefatos: dict[str, str] = field(default_factory=dict[str, str])
    feedback: str = ""


@dataclass(frozen=True)
class HarnessSaida:
    aprovadas: list[str] = field(default_factory=list[str])
    reprovadas: list[str] = field(default_factory=list[str])
    aprovado_pelo_avaliador: bool = False
    completa: bool = False
    verde: bool = False
    funcionalidades: int = 0
    feedback: str = ""
    violacoes: int = 0
    sessoes: int = 0
    tokens_entrada: int = 0
    tokens_saida: int = 0
    custo_usd: float = 0.0


@dataclass(frozen=True)
class AchadoDto:
    revisor: str
    severidade: str
    mensagem: str
    arquivo: str = ""
    linha: int = 0
    risco: int = 1


@dataclass(frozen=True)
class PoliticaDto:
    por_intent_usd: float = 0.0  # 0 = sem teto
    max_sessoes: int = 0
    declarada: bool = False


@dataclass(frozen=True)
class RevisaoEntrada:
    repositorio: str
    intent_id: str
    slug: str
    artefatos: dict[str, str] = field(default_factory=dict[str, str])
    labels: list[str] = field(default_factory=list[str])
    numero: int = 0


@dataclass(frozen=True)
class RevisaoSaida:
    tier: int = 3
    motivos: list[str] = field(default_factory=list[str])
    achados: list[AchadoDto] = field(default_factory=list[AchadoDto])
    review_md: str = ""
    resumos: dict[str, str] = field(default_factory=dict[str, str])
    tokens_entrada: int = 0
    tokens_saida: int = 0
    custo_usd: float = 0.0


@dataclass(frozen=True)
class DeployEntrada:
    repositorio: str
    intent_id: str
    slug: str
    branch_pronta: bool = False


@dataclass(frozen=True)
class PrEntrada:
    repositorio: str
    intent_id: str
    slug: str
    titulo: str
    corpo: str


class ExecutorDeEtapa(Protocol):
    async def __call__(self, entrada: EtapaEntrada) -> EtapaSaida: ...


DESFECHOS_CONCLUIDOS = frozenset(
    {"concluida", "artefatos_publicados", "verificada", "aprovada", "mesclada"}
)


class DeliveryActivities:
    """Agrupa as activities com o executor, o publicador e as métricas injetados."""

    def __init__(
        self,
        executor: ExecutorDeEtapa,
        intervalo_heartbeat_s: float = 5.0,
        publicador: PublicadorDeEntrega | None = None,
        metricas: MetricasForja | None = None,
        harness: Harness | None = None,
        revisor: RevisarEntrega | None = None,
        leitura: LeituraDeRevisao | None = None,
        escrita: EscritaDeRevisao | None = None,
    ) -> None:
        self._revisor = revisor
        self._leitura = leitura
        self._escrita = escrita
        self._harness_impl = harness
        self._executor = executor
        self._intervalo = intervalo_heartbeat_s
        self._publicador = publicador
        self._metricas = metricas

    def _medir(self, saida: EtapaSaida) -> None:
        self._medir_uso(UsoModelo(saida.tokens_entrada, saida.tokens_saida, saida.custo_usd))

    def _medir_uso(self, uso: UsoModelo) -> None:
        if self._metricas is not None:
            self._metricas.custo_usd.inc(uso.custo_usd)
            self._metricas.tokens.labels("entrada").inc(uso.tokens_entrada)
            self._metricas.tokens.labels("saida").inc(uso.tokens_saida)

    def _pub(self) -> PublicadorDeEntrega:
        if self._publicador is None:
            raise ApplicationError("publicador não configurado", non_retryable=True)
        return self._publicador

    @activity.defn(name="publicar_comentario")
    async def publicar_comentario(self, entrada: PublicarEntrada) -> str:
        """Escrita externa do fluxo; idempotente por `chave`."""
        return await self._pub().comentar(
            entrada.repositorio, entrada.numero, entrada.corpo, entrada.chave
        )

    @activity.defn(name="commitar_artefato")
    async def commitar_artefato(self, entrada: ArtefatoEntrada) -> str:
        info = activity.info()
        mensagem = (
            f"forja({entrada.etapa}): {entrada.nome}\n\n"
            f"Intent-Id: {entrada.intent_id}\nRun-Id: {info.workflow_run_id}\n"
            "Co-Authored-By: Forja <forja@users.noreply.github.com>"
        )
        destino = DestinoDaEntrega(entrada.repositorio, entrada.intent_id, entrada.slug)
        return await self._pub().commitar_artefato(
            destino, entrada.nome, entrada.conteudo, mensagem
        )

    @activity.defn(name="ler_artefato")
    async def ler_artefato(self, entrada: ArtefatoEntrada) -> str:
        """Versão da branch (um humano pode ter editado); vazio quando não há."""
        destino = DestinoDaEntrega(entrada.repositorio, entrada.intent_id, entrada.slug)
        return await self._pub().ler_artefato(destino, entrada.nome) or ""

    @activity.defn(name="abrir_pr")
    async def abrir_pr(self, entrada: PrEntrada) -> str:
        destino = DestinoDaEntrega(entrada.repositorio, entrada.intent_id, entrada.slug)
        return await self._pub().abrir_pr(destino, entrada.titulo, entrada.corpo)

    # --- revisão e deploy (M5) ---------------------------------------------------------

    def _revisao(self) -> RevisarEntrega:
        if self._revisor is None:
            raise ApplicationError("revisão não configurada", non_retryable=True)
        return self._revisor

    def _leit(self) -> LeituraDeRevisao:
        if self._leitura is None:
            raise ApplicationError("leitura de revisão não configurada", non_retryable=True)
        return self._leitura

    def _escr(self) -> EscritaDeRevisao:
        if self._escrita is None:
            raise ApplicationError("escrita de revisão não configurada", non_retryable=True)
        return self._escrita

    @activity.defn(name="carregar_politica")
    async def carregar_politica(self, repositorio: str) -> PoliticaDto:
        if self._leitura is None:
            return PoliticaDto()
        p = await self._leitura.politica(repositorio)
        o = p.orcamento
        return PoliticaDto(o.por_intent_usd or 0.0, o.max_sessoes_por_intent or 0, p.declarada)

    @activity.defn(name="revisar")
    async def revisar(self, e: RevisaoEntrada) -> RevisaoSaida:
        revisor = self._revisao()
        politica = await self._leit().politica(e.repositorio)
        feita = await self._com_heartbeat(
            revisor.executar(
                e.repositorio,
                nome_da_branch(e.intent_id, e.slug),
                e.artefatos.get("intent.md", ""),
                e.artefatos.get("spec.md", ""),
                e.labels,
                politica,
            ),
            "revisar",
        )
        self._medir_uso(feita.uso)
        r = feita.resultado
        return RevisaoSaida(
            tier=int(r.tier),
            motivos=list(r.classificacao.motivos),
            achados=[
                AchadoDto(
                    a.revisor,
                    a.severidade.value,
                    a.mensagem,
                    a.arquivo or "",
                    a.linha or 0,
                    int(a.risco),
                )
                for a in r.achados
            ],
            review_md=feita.review_md,
            tokens_entrada=feita.uso.tokens_entrada,
            tokens_saida=feita.uso.tokens_saida,
            custo_usd=feita.uso.custo_usd,
        )

    @activity.defn(name="publicar_checks")
    async def publicar_checks(self, e: RevisaoEntrada, achados: list[AchadoDto]) -> str:
        """Um check run por revisor, no commit atual da branch (depois do review.md)."""
        self._revisao()
        diff = await self._leit().diff_da_entrega(
            e.repositorio, nome_da_branch(e.intent_id, e.slug)
        )
        concluidos: list[str] = []
        for nome in REVISORES:
            dos_dele = tuple(
                Achado(
                    a.revisor,
                    Severidade(a.severidade),
                    a.mensagem,
                    a.arquivo or None,
                    a.linha or None,
                    Tier(a.risco),
                )
                for a in achados
                if a.revisor == nome
            )
            concluidos.append(
                await self._escr().check_run(
                    e.repositorio,
                    diff.head_sha,
                    nome,
                    dos_dele,
                    f"{len(dos_dele)} achado(s)",
                    e.intent_id,
                )
            )
        return ",".join(concluidos)

    @activity.defn(name="estado_dos_checks")
    async def estado_dos_checks(self, e: DeployEntrada) -> str:
        diff = await self._leit().diff_da_entrega(
            e.repositorio, nome_da_branch(e.intent_id, e.slug)
        )
        return await self._leit().estado_dos_checks(e.repositorio, diff.head_sha)

    @activity.defn(name="marcar_pronto")
    async def marcar_pronto(self, e: DeployEntrada) -> str:
        numero = await self._leit().numero_do_pr(e.repositorio, nome_da_branch(e.intent_id, e.slug))
        if numero is None:
            return "sem_pr"
        return await self._escr().marcar_pr_pronto(e.repositorio, numero, e.intent_id)

    @activity.defn(name="mesclar")
    async def mesclar(self, e: DeployEntrada) -> str:
        branch = nome_da_branch(e.intent_id, e.slug)
        numero = await self._leit().numero_do_pr(e.repositorio, branch)
        if numero is None:
            return "sem_pr"
        diff = await self._leit().diff_da_entrega(e.repositorio, branch)
        await self._escr().marcar_pr_pronto(e.repositorio, numero, e.intent_id)
        return await self._escr().mesclar_pr(e.repositorio, numero, diff.head_sha, e.intent_id)

    @activity.defn(name="registrar_desfecho")
    async def registrar_desfecho(self, desfecho: str) -> None:
        if self._metricas is None:
            return
        if desfecho in DESFECHOS_CONCLUIDOS:
            self._metricas.concluidas.inc()
        elif desfecho == "erro":
            self._metricas.com_erro.inc()

    async def _com_heartbeat[T](self, coro: Awaitable[T], detalhe: str) -> T:
        """O cancelamento só chega à activity pelo heartbeat; por isso o batimento roda enquanto
        o trabalho acontece, e o trabalho é cancelado junto."""
        trabalho = asyncio.ensure_future(coro)
        try:
            while True:
                activity.heartbeat(detalhe)
                feito, _ = await asyncio.wait({trabalho}, timeout=self._intervalo)
                if feito:
                    return trabalho.result()
        finally:
            if not trabalho.done():
                trabalho.cancel()
                await asyncio.gather(trabalho, return_exceptions=True)

    @activity.defn(name="executar_etapa")
    async def executar_etapa(self, entrada: EtapaEntrada) -> EtapaSaida:
        saida = await self._com_heartbeat(self._executor(entrada), entrada.etapa)
        self._medir(saida)
        return saida

    def _harness(self) -> Harness:
        if self._harness_impl is None:
            raise ApplicationError("harness não configurado", non_retryable=True)
        return self._harness_impl

    def _ctx(self, e: HarnessEntrada) -> ContextoDaEntrega:
        return ContextoDaEntrega(
            e.repositorio,
            e.intent_id,
            nome_da_branch(e.intent_id, e.slug),
            activity.info().workflow_run_id or "",
        )

    @activity.defn(name="harness_inicializar")
    async def harness_inicializar(self, e: HarnessEntrada) -> HarnessSaida:
        lista, uso = await self._com_heartbeat(
            self._harness().inicializar(
                self._ctx(e), e.artefatos["spec.md"], e.artefatos["plan.md"]
            ),
            "inicializar",
        )
        self._medir_uso(uso)
        return HarnessSaida(
            completa=lista.completa,
            funcionalidades=len(lista.features),
            tokens_entrada=uso.tokens_entrada,
            tokens_saida=uso.tokens_saida,
            custo_usd=uso.custo_usd,
        )

    @activity.defn(name="harness_bloco")
    async def harness_bloco(self, e: HarnessEntrada) -> HarnessSaida:
        r = await self._com_heartbeat(
            self._harness().executar_bloco(self._ctx(e), e.bloco, e.artefatos, e.feedback),
            f"bloco {e.bloco}",
        )
        self._medir_uso(r.uso)
        return HarnessSaida(
            sessoes=r.sessoes,
            aprovadas=list(r.aprovadas),
            reprovadas=list(r.reprovadas),
            aprovado_pelo_avaliador=r.aprovado_pelo_avaliador,
            completa=r.completa,
            feedback=r.feedback[:4000],
            violacoes=len(r.violacoes),
            tokens_entrada=r.uso.tokens_entrada,
            tokens_saida=r.uso.tokens_saida,
            custo_usd=r.uso.custo_usd,
        )

    @activity.defn(name="harness_verificar")
    async def harness_verificar(self, e: HarnessEntrada) -> HarnessSaida:
        v = await self._com_heartbeat(self._harness().verificar(self._ctx(e)), "verificar")
        return HarnessSaida(
            verde=v.verde,
            reprovadas=[f for f, ok in v.resultados.items() if not ok],
            aprovadas=[f for f, ok in v.resultados.items() if ok],
        )


# Referência para o workflow (nome estável da activity, sem importar a instância).
executar_etapa = DeliveryActivities.executar_etapa
