# pyright: basic
from __future__ import annotations

import asyncio
from typing import Any

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
            "" if aprovadas else "teste sem passar: f1", completa, (), sessoes=1,
            uso=self._Uso(2, 2, 0.2),
        )  # fmt: skip

    async def verificar(self, ctx):
        self.chamadas.append("verificar")
        return self._Verif(self.verde, {"f1": self.verde})


class LeituraFalsa:
    """O GitHub visto pela revisão: diff, política da branch padrão, checks e número do PR."""

    def __init__(self, politica=None, caminhos=("docs/a.md",), checks=("verde",)) -> None:
        from forja.domain.politica import Politica
        from forja.domain.revisao import ArquivoDoDiff, DiffDaEntrega

        self._politica = politica or Politica.de_dict(
            {
                "risk_tiers": {
                    "high": {"paths": ["infra/**"]},
                    "medium": {"paths": ["src/**"], "max_diff_lines": 400},
                    "low": {"paths": ["docs/**"]},
                },
                "budgets": {"per_intent_usd": 100.0, "max_sessions_per_intent": 50},
            }
        )
        self.diff = DiffDaEntrega(
            tuple(ArquivoDoDiff(c, "added", 3, 0, "+x") for c in caminhos), "a" * 40
        )
        self.checks = list(checks)
        # Pontas lidas da ref: a primeira é a pós-review; a lista permite simular "a branch andou".
        self.pontas = ["b" * 40]
        self.avanco_fixo: Any = None
        self.heads_lidos = 0
        self.numero_do_pr_fixo: int | None = 7

    async def head_da_branch(self, repositorio, branch):
        self.heads_lidos += 1
        return self.pontas.pop(0) if len(self.pontas) > 1 else self.pontas[0]

    async def avanco(self, repositorio, de_sha, para_sha):
        from forja.domain.revisao import AvancoDaBranch

        if self.avanco_fixo is not None:
            return self.avanco_fixo
        return AvancoDaBranch(1, (".forja/0123456789abcdef/review.md",))

    async def diff_da_entrega(self, repositorio, branch):
        return self.diff

    async def politica(self, repositorio):
        return self._politica

    async def estado_dos_checks(self, repositorio, sha):
        return self.checks.pop(0) if len(self.checks) > 1 else self.checks[0]

    async def numero_do_pr(self, repositorio, branch):
        return self.numero_do_pr_fixo


class EscritaFalsa:
    def __init__(self) -> None:
        self.checks: list[tuple[str, str]] = []
        self.prontos: list[int] = []
        self.merges: list[int] = []

    async def check_run(self, repositorio, head_sha, nome, achados, resumo, chave):
        from forja.domain.revisao import Severidade

        bloq = any(a.severidade is Severidade.BLOQUEANTE for a in achados)
        conclusao = "failure" if bloq else ("neutral" if achados else "success")
        self.checks.append((nome, conclusao))
        return conclusao

    async def marcar_pr_pronto(self, repositorio, numero, chave):
        self.prontos.append(numero)
        return "publicado"

    async def mesclar_pr(self, repositorio, numero, sha, chave):
        self.merges.append(numero)
        return "publicado"


class RevisorFalso:
    def __init__(self, nome: str, achados=()) -> None:
        self.nome, self.achados = nome, tuple(achados)

    async def revisar(self, repositorio, intent_md, spec_md, diff):
        from forja.application.portas.agente import UsoModelo
        from forja.application.portas.revisao import RevisaoDeUmRevisor

        return RevisaoDeUmRevisor(self.achados, f"resumo de {self.nome}", UsoModelo(1, 1, 0.01))


def pilha_de_revisao(leitura=None, escrita=None, achados_por_revisor=None):
    from forja.application.casos_de_uso.revisao import RevisarEntrega
    from forja.domain.revisao import REVISORES

    leitura = leitura or LeituraFalsa()
    escrita = escrita or EscritaFalsa()
    achados_por_revisor = achados_por_revisor or {}
    revisor = RevisarEntrega(
        [RevisorFalso(n, achados_por_revisor.get(n, ())) for n in REVISORES], leitura
    )
    return revisor, leitura, escrita
