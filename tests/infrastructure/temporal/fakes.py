# pyright: basic
from __future__ import annotations

import asyncio

from forja.application.portas.publicador import DestinoDaEntrega, ResultadoPublicacao
from forja.infrastructure.temporal.activities import EtapaEntrada, EtapaSaida


class ExecutorFalso:
    """Faz o papel dos agentes: texto fixo por etapa, com pontos em aberto configuráveis."""

    def __init__(self, pontos_em_aberto: int = 0, liberar: asyncio.Event | None = None) -> None:
        self.pontos = pontos_em_aberto
        self.liberar = liberar
        self.entradas: list[EtapaEntrada] = []

    def etapas(self, intent_id: str) -> list[str]:
        """Etapas da entrega (workflows vizinhos do módulo usam a mesma fila)."""
        return [e.etapa for e in self.entradas if e.intent_id == intent_id]

    async def __call__(self, entrada: EtapaEntrada) -> EtapaSaida:
        self.entradas.append(entrada)
        textos = {"plan": "# intent\n", "design": "# spec\n", "build": "# plan\n"}
        pontos = self.pontos if entrada.etapa == "design" else 0
        if self.liberar is not None and entrada.etapa == "plan":
            await self.liberar.wait()
        return EtapaSaida(entrada.etapa, "falso", textos.get(entrada.etapa, ""), pontos, 10, 5, 0.5)


class PublicadorFalso:
    def __init__(self) -> None:
        self.comentarios: list[tuple[str, str]] = []
        self.commits: list[tuple[str, str]] = []
        self.prs: list[tuple[str, str]] = []
        self.arquivos: dict[str, str] = {}
        self.falha_na_leitura = False

    async def comentar(
        self, repositorio: str, numero: int, corpo: str, chave: str
    ) -> ResultadoPublicacao:
        self.comentarios.append((chave, corpo))
        return "publicado"

    async def commitar_artefato(
        self, destino: DestinoDaEntrega, nome: str, conteudo: str, mensagem: str
    ) -> ResultadoPublicacao:
        self.commits.append((nome, mensagem))
        self.arquivos[nome] = conteudo
        return "publicado"

    async def ler_artefato(self, destino: DestinoDaEntrega, nome: str) -> str | None:
        if self.falha_na_leitura:
            raise RuntimeError("github fora")
        return self.arquivos.get(nome + ":editado")

    async def abrir_pr(self, destino: DestinoDaEntrega, titulo: str, corpo: str) -> str:
        self.prs.append((titulo, corpo))
        return "https://github.test/pr/1"


class HarnessFalso:
    """Faz o papel do Build de longa duração: resultados roteirizados por bloco."""

    def __init__(self, blocos=None, verde=True, atraso=0.0) -> None:
        from forja.application.portas.agente import UsoModelo
        from forja.application.portas.harness import ResultadoDaVerificacao, ResultadoDoBloco
        from forja.domain.harness import ContratoDeSprint, Criterio

        self._Bloco, self._Verif, self._Uso = ResultadoDoBloco, ResultadoDaVerificacao, UsoModelo
        self._contrato = ContratoDeSprint(1, ("f1",), ("e",), ("v",), dict.fromkeys(Criterio, 7))
        self.blocos = list(blocos or [(("f1",), True)])
        self.verde = verde
        self.atraso = atraso
        self.feedbacks: list[str] = []
        self.chamadas: list[str] = []

    async def inicializar(self, ctx, spec_md, plano_md):
        from forja.domain.harness import Feature, FeatureList

        self.chamadas.append("inicializar")
        f = Feature("f1", "c", "d", ("p",), ("pytest",))
        return FeatureList((f,)), self._Uso(1, 1, 0.1)

    async def executar_bloco(self, ctx, bloco, artefatos, feedback):
        self.chamadas.append(f"bloco{bloco}")
        self.feedbacks.append(feedback)
        await asyncio.sleep(self.atraso)
        aprovadas, completa = self.blocos.pop(0) if self.blocos else ((), False)
        return self._Bloco(
            self._contrato, tuple(aprovadas), () if aprovadas else ("f1",), bool(aprovadas),
            "" if aprovadas else "teste sem passar: f1", completa, (), self._Uso(2, 2, 0.2),
        )  # fmt: skip

    async def verificar(self, ctx):
        self.chamadas.append("verificar")
        return self._Verif(self.verde, {"f1": self.verde})
