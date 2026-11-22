"""Agentes do SDLC (M3): Intérprete, Spec (orquestrador + pesquisadores) e Planner.

Nenhum tem ferramenta (ADR 0036): o repositório e o RAG chegam por código, como dado
delimitado; a saída é JSON validado por schema e renderizada em Markdown por código.
"""

from __future__ import annotations

import asyncio
from importlib import resources

from forja.application.portas.agente import UsoModelo
from forja.application.portas.sdlc import (
    FonteRecuperada,
    ListadorDeArquivos,
    Pedido,
    PesquisaDeConhecimento,
    Resultado,
)
from forja.domain.artefatos import Fonte, IntentMd, Plano, Spec, linha_unica
from forja.domain.seguranca import dado_nao_confiavel
from forja.infrastructure.agents.esquemas import (
    AchadosSaida,
    IntentSaida,
    PlanoSaida,
    SpecSaida,
)
from forja.infrastructure.agents.estruturado import AgenteEstruturado, somar

# (foco, tipo no índice): os pesquisadores da seção 5.4 (orquestrador-trabalhadores).
FOCOS: tuple[tuple[str, str], ...] = (("codigo", "codigo"), ("adrs", "adr"), ("docs", "doc"))
MAX_ARQUIVOS_NO_PROMPT = 1500
TRECHO_MAX = 1500


def carregar_prompt(nome: str) -> str:
    return (
        resources.files("forja.infrastructure.agents")
        .joinpath(f"prompts/{nome}.md")
        .read_text("utf-8")
    )


class InterpreteAgente:
    def __init__(self, agente: AgenteEstruturado[IntentSaida]) -> None:
        self._agente = agente

    async def interpretar(self, pedido: Pedido) -> Resultado[IntentMd]:
        texto = (
            f"<titulo>{dado_nao_confiavel(pedido.titulo)}</titulo>\n"
            f"<corpo>{dado_nao_confiavel(pedido.corpo)}</corpo>"
        )
        origem = f"github:{pedido.repositorio}#{pedido.numero}"
        intent, uso = await self._agente.pedir(
            f"{pedido.repositorio}#{pedido.numero}",
            texto,
            lambda s: s.para_dominio(origem, pedido.url),
        )
        return Resultado(intent, uso)


def _bloco_de_fontes(fontes: list[FonteRecuperada]) -> str:
    return "\n".join(
        f'<fonte id="{f.id}" caminho="{dado_nao_confiavel(f.caminho)}">'
        f"{dado_nao_confiavel(f.texto[:TRECHO_MAX])}</fonte>"
        for f in fontes
    )


class EspecificadorMultiagente:
    """Líder + pesquisadores em paralelo (ADR 0017). A busca no RAG é feita aqui, por código;
    o agente só vê os trechos, e só pode citar o que foi recuperado."""

    def __init__(
        self,
        pesquisa: PesquisaDeConhecimento,
        pesquisador: AgenteEstruturado[AchadosSaida],
        redator: AgenteEstruturado[SpecSaida],
        k: int = 6,
    ) -> None:
        self._pesquisa = pesquisa
        self._pesquisador = pesquisador
        self._redator = redator
        self._k = k

    async def especificar(self, repositorio: str, intent_md: str) -> Resultado[Spec]:
        consulta = linha_unica(intent_md, 480)
        listas = await asyncio.gather(
            *(self._pesquisa.pesquisar(repositorio, consulta, tipo, self._k) for _, tipo in FOCOS)
        )
        disponiveis = {f.id: Fonte(f.id, f.caminho, f.commit) for lista in listas for f in lista}
        rodadas = await asyncio.gather(
            *(
                self._pesquisar(foco, intent_md, lista, disponiveis)
                for (foco, _), lista in zip(FOCOS, listas, strict=True)
                if lista
            )
        )
        uso = UsoModelo()
        blocos: list[str] = []
        for achados, u in rodadas:
            uso = somar(uso, u)
            blocos += achados
        texto = f"<intent>{dado_nao_confiavel(intent_md)}</intent>\n" + "\n".join(blocos)
        if not disponiveis:
            texto += "\n<aviso>nenhuma fonte recuperada do repositório; não cite fontes</aviso>"
        spec, u = await self._redator.pedir(
            repositorio, texto, lambda s: s.para_dominio(disponiveis)
        )
        return Resultado(spec, somar(uso, u))

    async def _pesquisar(
        self,
        foco: str,
        intent_md: str,
        fontes: list[FonteRecuperada],
        disponiveis: dict[str, Fonte],
    ) -> tuple[list[str], UsoModelo]:
        texto = (
            f"<foco>{foco}</foco>\n<intent>{dado_nao_confiavel(intent_md)}</intent>\n"
            + _bloco_de_fontes(fontes)
        )
        saida, uso = await self._pesquisador.pedir(f"pesquisa-{foco}", texto, lambda s: s)
        blocos: list[str] = []
        for a in saida.achados:
            # Citação inventada é descartada; o achado fica sem ela.
            validas = [f for f in a.fontes if f in disponiveis]
            blocos.append(
                f'<achado fontes="{",".join(validas)}">{dado_nao_confiavel(a.resumo)}</achado>'
            )
        return blocos, uso


class PlanejadorAgente:
    def __init__(self, agente: AgenteEstruturado[PlanoSaida], arquivos: ListadorDeArquivos) -> None:
        self._agente = agente
        self._arquivos = arquivos

    async def planejar(self, repositorio: str, intent_md: str, spec_md: str) -> Resultado[Plano]:
        arquivos = (await self._arquivos.listar(repositorio))[:MAX_ARQUIVOS_NO_PROMPT]
        texto = (
            f"<intent>{dado_nao_confiavel(intent_md)}</intent>\n"
            f"<spec>{dado_nao_confiavel(spec_md)}</spec>\n"
            f"<arquivos>{dado_nao_confiavel(chr(10).join(arquivos))}</arquivos>"
        )
        plano, uso = await self._agente.pedir(repositorio, texto, lambda s: s.para_dominio())
        return Resultado(plano, uso)
