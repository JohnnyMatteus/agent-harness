# pyright: basic
import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from forja.application.casos_de_uso.recuperar_conhecimento import RecuperarConhecimento
from forja.application.portas.agente import RespostaDoAgente
from forja.domain.knowledge import Escopo, TipoDeTrecho, Trecho
from forja.infrastructure.agents.arquivos_git import ListadorGit
from forja.infrastructure.agents.esquemas import IntentSaida, PlanoSaida, SpecSaida
from forja.infrastructure.agents.estruturado import (
    AgenteEstruturado,
    SaidaInvalida,
    extrair_json,
)
from forja.infrastructure.agents.executor_sdlc import ExecutorSdlc
from forja.infrastructure.agents.pesquisa_rag import PesquisaRag
from forja.infrastructure.knowledge.embedder_falso import EmbedderFalso
from forja.infrastructure.knowledge.memoria import IndiceEmMemoria
from forja.infrastructure.sandbox.repositorios import RepositoriosLocais
from forja.infrastructure.temporal.activities import EtapaEntrada


class RunnerRoteirizado:
    def __init__(self, *respostas: str) -> None:
        self.respostas = list(respostas)
        self.pedidos: list[str] = []

    async def executar(self, pedido: Any) -> RespostaDoAgente:
        self.pedidos.append(pedido.texto_nao_confiavel)
        return RespostaDoAgente(self.respostas.pop(0))


def test_extrair_json_aceita_cerca_e_texto_em_volta() -> None:
    assert extrair_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extrair_json('Aqui: {"a": {"b": 2}} fim') == {"a": {"b": 2}}
    for ruim in ("sem json", "{quebrado", "x" * 70_000):
        with pytest.raises(ValueError):  # noqa: PT011
            extrair_json(ruim)


async def test_saida_invalida_recebe_uma_reparacao_e_depois_falha() -> None:
    runner = RunnerRoteirizado("lixo", '{"problema": "p", "criterios_de_sucesso": []}')
    agente = AgenteEstruturado(runner, IntentSaida, "t")
    valor, _ = await agente.pedir("i", "texto", lambda s: s.problema)
    assert valor == "p" and "recusada" in runner.pedidos[1] and "recusada" not in runner.pedidos[0]
    ruim = AgenteEstruturado(RunnerRoteirizado("lixo", "lixo"), IntentSaida, "t")
    with pytest.raises(SaidaInvalida):
        await ruim.pedir("i", "texto", lambda s: s)


@pytest.mark.parametrize(
    "saida",
    [
        '{"problema": "p", "extra": 1}',
        '{"problema": "", "criterios_de_sucesso": []}',
        '{"problema": "p", "criterios_de_sucesso": [' + ",".join(['"c"'] * 21) + "]}",
        '{"problema": "' + "x" * 2001 + '"}',
    ],
)
async def test_schema_recusa_campo_extra_vazio_e_acima_do_teto(saida: str) -> None:
    agente = AgenteEstruturado(RunnerRoteirizado(saida, saida), IntentSaida, "t")
    with pytest.raises(SaidaInvalida):
        await agente.pedir("i", "t", lambda s: s)


def test_plano_e_spec_validam_no_dominio() -> None:
    with pytest.raises(Exception, match=r"caminho|segmento"):
        PlanoSaida.model_validate({"passos": [{"arquivo": "../x", "mudanca": "m"}]}).para_dominio()
    spec = SpecSaida.model_validate(
        {"requisitos": ["r"], "cenarios": [{"titulo": "t", "passos": ["Dado x"]}], "fontes": ["z"]}
    )
    with pytest.raises(ValueError, match="não foram recuperadas"):
        spec.para_dominio({})


async def test_executor_exige_artefato_anterior_e_etapa_conhecida() -> None:
    ex = ExecutorSdlc(None, SimpleNamespace(especificar=None), None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="repositório"):
        await ex(EtapaEntrada("i", "plan"))
    with pytest.raises(ValueError, match="ausente"):
        await ex(EtapaEntrada("i", "design", repositorio="a/b"))
    with pytest.raises(ValueError, match="sem executor"):
        await ex(EtapaEntrada("i", "test", repositorio="a/b"))


async def test_pesquisa_rag_so_enxerga_o_escopo_do_repositorio() -> None:
    indice, embedder = IndiceEmMemoria(), EmbedderFalso()
    for org, repo, conteudo in (
        ("acme", "loja", "validar senha"),
        ("acme", "outro", "validar senha"),
    ):
        escopo = Escopo(org, repo)
        t = Trecho(
            f"{repo}-1",
            escopo,
            "src/a.py",
            "python",
            TipoDeTrecho.CODIGO,
            "f",
            1,
            2,
            conteudo,
            "",
            "c" * 40,
        )
        indice.substituir_arquivo(escopo, "src/a.py", "v1", [(t, embedder.embutir([conteudo])[0])])
    pesquisa = PesquisaRag(RecuperarConhecimento(indice, embedder))
    achados = await pesquisa.pesquisar("acme/loja", "validar senha", "codigo", 5)
    assert [a.id for a in achados] == ["loja-1"]
    with pytest.raises(ValueError, match="inválido"):
        await pesquisa.pesquisar("../x", "q", None, 5)


async def test_listador_git_devolve_so_caminhos_seguros(tmp_path: Path) -> None:
    repo = tmp_path / "acme" / "loja"
    repo.mkdir(parents=True)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], cwd=repo, check=True)
    (repo / "a.py").write_text("x")
    (repo / "estranho;$(x).py").write_text("x")
    subprocess.run([*git, "add", "."], cwd=repo, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "i"], cwd=repo, check=True)
    arquivos = await ListadorGit(RepositoriosLocais(tmp_path)).listar("acme/loja")
    assert arquivos == ("a.py",)
    assert asyncio.iscoroutinefunction(ListadorGit.listar)


async def test_executor_leva_tokens_e_custo_das_sessoes_para_a_saida() -> None:
    from forja.application.portas.agente import UsoModelo
    from forja.application.portas.sdlc import Resultado
    from forja.domain.artefatos import IntentMd

    class Interprete:
        async def interpretar(self, pedido):
            return Resultado(IntentMd("p", (), "o"), UsoModelo(11, 7, 0.25))

    saida = await ExecutorSdlc(Interprete(), None, None)(  # type: ignore[arg-type]
        EtapaEntrada("i", "plan", repositorio="a/b")
    )
    assert (saida.tokens_entrada, saida.tokens_saida, saida.custo_usd) == (11, 7, 0.25)
