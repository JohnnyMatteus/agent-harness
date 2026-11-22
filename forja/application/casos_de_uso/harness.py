"""Build de longa duração (seção 5.3): Inicializador, blocos com contrato de sprint, grader de
código e verificação final. Cada passo roda num sandbox novo; a continuidade está nos artefatos
da branch (feature_list.json, progress.md, contrato) e no git, nunca no contexto do modelo."""

from __future__ import annotations

import asyncio
import shlex
from collections.abc import Callable
from pathlib import Path

from forja.application.portas.agente import UsoModelo
from forja.application.portas.area_de_trabalho import AreaDeTrabalho, RemotoGit
from forja.application.portas.harness import (
    Avaliacao,
    AvaliadorIndependente,
    ContextoDaEntrega,
    ExecutorDeSessao,
    Inicializador,
    PedidoDeAvaliacao,
    ResultadoDaVerificacao,
    ResultadoDoBloco,
)
from forja.application.portas.sandbox import EspecSandbox, Sandbox, SandboxAtivo, SandboxError
from forja.domain.artefatos import NomeDeArtefato, caminho_do_artefato, sanear_mensagem_de_commit
from forja.domain.erros import ErroDeDominio
from forja.domain.guardrails import Etapa, PoliticaDeSessao, auditar_mudancas
from forja.domain.harness import (
    ContratoDeSprint,
    Feature,
    FeatureList,
    decidir_bloco,
    exigir_so_passes_mudou,
    features_que_passam,
)

RODADAS_DE_CONTRATO = 3
TIMEOUT_DE_TESTE_S = 900.0


class SemAcordoNoContrato(ErroDeDominio):
    """Executor e Avaliador não chegaram a um contrato de sprint."""


class HarnessIndisponivel(ErroDeDominio):
    """Estado da branch não permite continuar (feature_list ausente ou adulterada)."""


def _somar(a: UsoModelo, b: UsoModelo) -> UsoModelo:
    return UsoModelo(
        a.tokens_entrada + b.tokens_entrada,
        a.tokens_saida + b.tokens_saida,
        a.custo_usd + b.custo_usd,
    )


async def destruir_mesmo_cancelado(sandbox: Sandbox, sessao_id: str) -> None:
    """Se a activity for cancelada (/forja stop, pânico), o sandbox ainda é destruído."""
    tarefa = asyncio.ensure_future(sandbox.destruir(sessao_id))
    try:
        await asyncio.shield(tarefa)
    except asyncio.CancelledError:
        await tarefa
        raise


class _Base:
    def __init__(
        self, sandbox: Sandbox, area: AreaDeTrabalho, remoto: RemotoGit, clone: Callable[[str], str]
    ) -> None:
        self._sandbox = sandbox
        self._area = area
        self._remoto = remoto
        self._clone = clone

    def _caminho(self, ctx: ContextoDaEntrega, nome: NomeDeArtefato) -> str:
        return caminho_do_artefato(ctx.intent_id, nome)

    async def _abrir(self, ctx: ContextoDaEntrega, acao: str) -> SandboxAtivo:
        sessao = f"{ctx.intent_id}-{acao}"
        await self._sandbox.destruir(sessao)
        ativo = await self._sandbox.criar(EspecSandbox(sessao, self._clone(ctx.repositorio)))
        try:
            await self._remoto.buscar(ctx.repositorio, ctx.branch, ativo.worktree)
            await self._area.garantir_branch(ativo.worktree, ctx.branch)
        except BaseException:
            await destruir_mesmo_cancelado(self._sandbox, sessao)
            raise
        return ativo

    async def _lista(self, ctx: ContextoDaEntrega, wt: Path) -> FeatureList:
        texto = await self._area.ler(wt, self._caminho(ctx, NomeDeArtefato.FEATURE_LIST))
        if texto is None:
            raise HarnessIndisponivel("feature_list.json ausente na branch da entrega")
        return FeatureList.de_json(texto)

    def _mensagem(self, ctx: ContextoDaEntrega, assunto: str, quem: str) -> str:
        return sanear_mensagem_de_commit(
            f"{assunto}\n\nIntent-Id: {ctx.intent_id}\nRun-Id: {ctx.run_id}\n"
            f"Co-Authored-By: {quem} <forja@users.noreply.github.com>"
        )

    async def _testar(self, ativo: SandboxAtivo, feature: Feature) -> bool:
        """Grader de código: o teste da funcionalidade passa (saída 0) ou não passa."""
        try:
            r = await ativo.executar(list(feature.comando_de_teste), timeout_s=TIMEOUT_DE_TESTE_S)
        except SandboxError:
            return False
        return r.codigo_saida == 0


class InicializarHarness(_Base):
    def __init__(
        self,
        sandbox: Sandbox,
        area: AreaDeTrabalho,
        remoto: RemotoGit,
        clone: Callable[[str], str],
        inicializador: Inicializador,
    ) -> None:
        super().__init__(sandbox, area, remoto, clone)
        self._inicializador = inicializador

    async def executar(
        self, ctx: ContextoDaEntrega, spec_md: str, plano_md: str
    ) -> tuple[FeatureList, UsoModelo]:
        ativo = await self._abrir(ctx, "init")
        try:
            wt = ativo.worktree
            existente = await self._area.ler(wt, self._caminho(ctx, NomeDeArtefato.FEATURE_LIST))
            if existente is not None:  # retentativa: a branch já foi inicializada
                return FeatureList.de_json(existente), UsoModelo()
            plano = await self._inicializador.inicializar(ctx.repositorio, spec_md, plano_md)
            comandos = "\n".join(shlex.join(c) for c in plano.comandos_de_setup)
            init = f"#!/bin/sh\nset -eu\n{comandos}\n" if comandos else "#!/bin/sh\nset -eu\n"
            await self._area.escrever(wt, self._caminho(ctx, NomeDeArtefato.INIT), init)
            await self._area.escrever(
                wt, self._caminho(ctx, NomeDeArtefato.FEATURE_LIST), plano.features.para_json()
            )
            await self._area.escrever(
                wt,
                self._caminho(ctx, NomeDeArtefato.PROGRESS),
                "# progress\n\nUma funcionalidade por sessão; o estado vive aqui, na "
                "feature_list.json e no git log.\n",
            )
            await self._area.commitar(wt, self._mensagem(ctx, "forja(init): harness", "Forja"))
            await self._remoto.enviar(ctx.repositorio, ctx.branch, wt)
            return plano.features, plano.uso
        finally:
            await destruir_mesmo_cancelado(self._sandbox, ativo.sessao_id)


class ExecutarBloco(_Base):
    def __init__(
        self,
        sandbox: Sandbox,
        area: AreaDeTrabalho,
        remoto: RemotoGit,
        clone: Callable[[str], str],
        executor: ExecutorDeSessao,
        avaliador: AvaliadorIndependente,
        tamanho_do_bloco: int = 3,
        ao_violar: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(sandbox, area, remoto, clone)
        self._executor = executor
        self._avaliador = avaliador
        self._tamanho = tamanho_do_bloco
        self._ao_violar = ao_violar

    async def executar(
        self,
        ctx: ContextoDaEntrega,
        bloco: int,
        artefatos: dict[str, str],
        feedback: str,
    ) -> ResultadoDoBloco:
        ativo = await self._abrir(ctx, f"bloco{bloco}")
        try:
            return await self._bloco(ativo, ctx, bloco, artefatos, feedback)
        finally:
            await destruir_mesmo_cancelado(self._sandbox, ativo.sessao_id)

    async def _bloco(
        self,
        ativo: SandboxAtivo,
        ctx: ContextoDaEntrega,
        bloco: int,
        artefatos: dict[str, str],
        feedback: str,
    ) -> ResultadoDoBloco:
        wt = ativo.worktree
        lista = await self._lista(ctx, wt)
        features = lista.bloco(self._tamanho)
        if not features:
            raise HarnessIndisponivel("não há funcionalidade pendente")
        contrato, uso = await self._negociar(ctx, bloco, lista)
        await self._area.escrever(
            wt, self._caminho(ctx, NomeDeArtefato.CONTRATO), contrato.para_json()
        )
        # O contrato é do harness: entra no commit antes da sessão e não conta como mudança dela.
        await self._area.commitar(
            wt, self._mensagem(ctx, f"forja(bloco {bloco}): contrato de sprint", "Forja")
        )
        por_id = {f.id: f for f in lista.features}
        violacoes: list[str] = []
        resumos: list[str] = []
        for feature_id in contrato.features:  # uma funcionalidade por sessão
            sessao = await self._sessao(ativo, ctx, por_id[feature_id], feedback)
            uso = _somar(uso, sessao[0])
            violacoes += sessao[1]
            resumos.append(f"{feature_id}: {sessao[2]}")
        resultados = {fid: await self._testar(ativo, por_id[fid]) for fid in contrato.features}
        pedido = PedidoDeAvaliacao(
            contrato,
            artefatos.get("intent.md", ""),
            artefatos.get("spec.md", ""),
            artefatos.get("plan.md", ""),
            "\n".join(resumos),
            resultados,
        )
        avaliacao: Avaliacao = await self._avaliador.avaliar(ativo, ctx.repositorio, pedido)
        uso = _somar(uso, avaliacao.uso)
        veredito = decidir_bloco(contrato.limiares, avaliacao.notas)
        passam = features_que_passam(veredito, resultados, contrato)
        nova = lista.com_passes(passam)
        exigir_so_passes_mudou(lista, nova)
        await self._area.escrever(
            wt, self._caminho(ctx, NomeDeArtefato.FEATURE_LIST), nova.para_json()
        )
        await self._area.commitar(
            wt, self._mensagem(ctx, f"forja(bloco {bloco}): resultado", "Forja Avaliador")
        )
        await self._remoto.enviar(ctx.repositorio, ctx.branch, wt)
        texto = "\n".join(
            [f"{c.value}: {avaliacao.feedback[c]}" for c in avaliacao.feedback]
            + [f"defeito: {d}" for d in avaliacao.defeitos]
            + [f"teste sem passar: {fid}" for fid, ok in resultados.items() if not ok]
        )
        return ResultadoDoBloco(
            contrato=contrato,
            aprovadas=tuple(sorted(passam)),
            reprovadas=tuple(f for f in contrato.features if f not in passam),
            aprovado_pelo_avaliador=veredito.aprovado,
            feedback=texto,
            completa=nova.completa,
            violacoes=tuple(violacoes),
            uso=uso,
        )

    async def _negociar(
        self, ctx: ContextoDaEntrega, bloco: int, lista: FeatureList
    ) -> tuple[ContratoDeSprint, UsoModelo]:
        features = lista.bloco(self._tamanho)
        ajustes: list[str] = []
        uso = UsoModelo()
        for _ in range(RODADAS_DE_CONTRATO):
            proposta = await self._executor.propor_contrato(
                ctx.repositorio, bloco, features, ajustes
            )
            contrato = proposta.contrato
            contrato.exigir_dentro_de(lista, self._tamanho)
            revisao = await self._avaliador.revisar_contrato(ctx.repositorio, contrato)
            uso = _somar(_somar(uso, proposta.uso), revisao.uso)
            if revisao.acordo:
                return contrato, uso
            ajustes = list(revisao.ajustes)
        raise SemAcordoNoContrato(f"sem acordo após {RODADAS_DE_CONTRATO} rodadas")

    async def _sessao(
        self, ativo: SandboxAtivo, ctx: ContextoDaEntrega, feature: Feature, feedback: str
    ) -> tuple[UsoModelo, list[str], str]:
        wt = ativo.worktree
        base = await self._area.head(wt)
        testes, links = await self._area.arquivos_de_teste_e_links(wt)
        politica = PoliticaDeSessao(Etapa.EXECUTOR, ctx.intent_id, testes, links)
        contexto = await self._contexto(ativo, ctx)
        resultado = await self._executor.executar_sessao(
            ativo, ctx.repositorio, ctx.intent_id, feature, contexto, feedback, politica
        )
        mudancas = await self._area.mudancas(wt, base)
        violacoes = list(auditar_mudancas(politica, mudancas))
        progress = self._caminho(ctx, NomeDeArtefato.PROGRESS)
        if not violacoes and progress not in {m.caminho for m in mudancas}:
            violacoes.append(f"{progress}: não foi atualizado na sessão")
        if violacoes:
            await self._area.descartar(wt, base)  # trapaça ou sessão suja: nada fica
            for v in violacoes:
                if self._ao_violar is not None:
                    self._ao_violar(v)
            return resultado.uso, violacoes, "sessão descartada: " + "; ".join(violacoes)[:300]
        await self._area.commitar(
            wt, self._mensagem(ctx, resultado.mensagem_de_commit, "Forja Executor")
        )
        return resultado.uso, [], resultado.resumo[:300]

    async def _contexto(self, ativo: SandboxAtivo, ctx: ContextoDaEntrega) -> str:
        """Passos 1, 2 e 4 da seção 5.3, por código: branch, progress/log e estado do ambiente."""
        wt = ativo.worktree
        progress = await self._area.ler(wt, self._caminho(ctx, NomeDeArtefato.PROGRESS)) or ""
        log = await self._area.log_recente(wt, 10)
        lista = await self._lista(ctx, wt)
        estado = "ambiente ok"
        init = self._caminho(ctx, NomeDeArtefato.INIT)
        r = None
        if await self._area.ler(wt, init) is not None:
            r = await ativo.executar(["bash", init], timeout_s=TIMEOUT_DE_TESTE_S)
        if r is not None and r.codigo_saida != 0:
            estado = f"init.sh falhou ({r.codigo_saida}): {r.stderr[-400:]}"
        elif lista.comando_de_fumaca:
            fumaca = await ativo.executar(
                list(lista.comando_de_fumaca), timeout_s=TIMEOUT_DE_TESTE_S
            )
            if fumaca.codigo_saida != 0:
                estado = f"teste de fumaça quebrado antes da sessão: {fumaca.stdout[-400:]}"
        return f"branch: {ctx.branch}\nestado: {estado}\nprogress.md:\n{progress}\nlog:\n{log}"


class VerificarEntrega(_Base):
    """Test (seção 5.1): todos os testes de funcionalidade, no estado da branch."""

    async def executar(self, ctx: ContextoDaEntrega) -> ResultadoDaVerificacao:
        ativo = await self._abrir(ctx, "verificar")
        try:
            lista = await self._lista(ctx, ativo.worktree)
            resultados = {f.id: await self._testar(ativo, f) for f in lista.features}
            return ResultadoDaVerificacao(lista.completa and all(resultados.values()), resultados)
        finally:
            await destruir_mesmo_cancelado(self._sandbox, ativo.sessao_id)


class HarnessDaEntrega:
    """Fachada das três etapas do Build para as activities."""

    def __init__(
        self, inicializar: InicializarHarness, bloco: ExecutarBloco, verificar: VerificarEntrega
    ) -> None:
        self._inicializar = inicializar
        self._bloco = bloco
        self._verificar = verificar

    async def inicializar(
        self, ctx: ContextoDaEntrega, spec_md: str, plano_md: str
    ) -> tuple[FeatureList, UsoModelo]:
        return await self._inicializar.executar(ctx, spec_md, plano_md)

    async def executar_bloco(
        self, ctx: ContextoDaEntrega, bloco: int, artefatos: dict[str, str], feedback: str
    ) -> ResultadoDoBloco:
        return await self._bloco.executar(ctx, bloco, artefatos, feedback)

    async def verificar(self, ctx: ContextoDaEntrega) -> ResultadoDaVerificacao:
        return await self._verificar.executar(ctx)
