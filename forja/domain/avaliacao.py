"""Evals (seção 11, ADR 0018): pass@k, pass^k e o rótulo do relatório.

Tarefa = entrada + critério de sucesso conferido no AMBIENTE (git, arquivo, teste), nunca no que o
agente diz. Tentativa = uma execução. Estas contas valem para qualquer executor; o relatório diz
qual rodou, e com executor falso o resultado mede só o harness, nunca a qualidade de um agente.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import comb

from forja.domain.erros import ErroDeDominio

EXECUTOR_FALSO = "falso"
EXECUTOR_NENHUM = "nenhum (código de produção, sem modelo)"
AVISO_EXECUTOR_FALSO = (
    "Executor falso: este resultado mede só o HARNESS (regressão determinística). Taxa, pass@k e "
    "ablação com modelo falso NÃO dizem nada sobre a qualidade de um agente."
)


class AvaliacaoInvalida(ErroDeDominio):
    """Entrada de eval incoerente (contagens impossíveis, relatório sem tarefa)."""


def _validar(n: int, c: int, k: int) -> None:
    if n < 1 or not 0 <= c <= n or not 1 <= k <= n:
        raise AvaliacaoInvalida(f"contagens impossíveis: n={n}, c={c}, k={k}")


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probabilidade de PELO MENOS UMA de k tentativas sorteadas entre as n dar certo, com c
    sucessos (estimador não viesado). Para tarefas em que uma boa solução basta."""
    _validar(n, c, k)
    if n - c < k:
        return 1.0
    return 1.0 - comb(n - c, k) / comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """Probabilidade de TODAS as k tentativas sorteadas entre as n darem certo (pass^k). Para o
    que precisa ser consistente (hooks de segurança, máquina de estados)."""
    _validar(n, c, k)
    return comb(c, k) / comb(n, k)


@dataclass(frozen=True, slots=True)
class ResultadoDeTarefa:
    tarefa: str
    tentativas: int
    sucessos: int

    def __post_init__(self) -> None:
        _validar(self.tentativas, self.sucessos, 1)


@dataclass(frozen=True, slots=True)
class Relatorio:
    """Resultado de uma suíte. `executor` é obrigatório: sem dizer quem rodou, não há relatório."""

    suite: str
    executor: str
    tarefas: tuple[ResultadoDeTarefa, ...]

    def __post_init__(self) -> None:
        if not self.executor.strip():
            raise AvaliacaoInvalida("o relatório precisa dizer qual executor rodou")
        if not self.tarefas:
            raise AvaliacaoInvalida("nenhuma tarefa rodou: não há relatório (isso é falha)")

    @property
    def mede_qualidade_de_agente(self) -> bool:
        return self.executor not in (EXECUTOR_FALSO, EXECUTOR_NENHUM)

    def taxa(self) -> float:
        total = sum(t.tentativas for t in self.tarefas)
        return sum(t.sucessos for t in self.tarefas) / total

    def pass_at_k(self, k: int) -> float:
        return sum(pass_at_k(t.tentativas, t.sucessos, k) for t in self.tarefas) / len(self.tarefas)

    def pass_hat_k(self, k: int) -> float:
        return sum(pass_hat_k(t.tentativas, t.sucessos, k) for t in self.tarefas) / len(
            self.tarefas
        )

    def texto(self, k: int = 1) -> str:
        cabecalho = f"suíte {self.suite} | executor: {self.executor}"
        corpo = (
            f"{len(self.tarefas)} tarefas | taxa {self.taxa():.3f} | pass@{k} "
            f"{self.pass_at_k(k):.3f} | pass^{k} {self.pass_hat_k(k):.3f}"
        )
        aviso = "" if self.mede_qualidade_de_agente else f"\n{AVISO_EXECUTOR_FALSO}"
        return f"{cabecalho}\n{corpo}{aviso}"
