"""Portas da revisão e do deploy: leitura do GitHub (diff, política, checks) e escrita (check
runs, PR pronto, merge). A escrita passa pelo publicador (dry-run e idempotência)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from forja.application.portas.agente import UsoModelo
from forja.domain.politica import Politica
from forja.domain.revisao import Achado, AvancoDaBranch, DiffDaEntrega

EstadoDosChecks = Literal["verde", "pendente", "falhou", "sem_externos"]


@dataclass(frozen=True, slots=True)
class RevisaoDeUmRevisor:
    achados: tuple[Achado, ...]
    resumo: str
    uso: UsoModelo = field(default_factory=UsoModelo)


class Revisor(Protocol):
    nome: str

    async def revisar(
        self, repositorio: str, intent_md: str, spec_md: str, diff: DiffDaEntrega
    ) -> RevisaoDeUmRevisor: ...


class LeituraDeRevisao(Protocol):
    async def head_da_branch(self, repositorio: str, branch: str) -> str:
        """SHA da ponta da branch, lido da ref."""
        ...

    async def diff_da_entrega(self, repositorio: str, branch: str) -> DiffDaEntrega:
        """Diff contra a branch padrão, calculado pelo SHA da ponta (`head_sha`)."""
        ...

    async def avanco(self, repositorio: str, de_sha: str, para_sha: str) -> AvancoDaBranch: ...

    async def politica(self, repositorio: str) -> Politica:
        """`.forja/policy.yaml` da branch PADRÃO (nunca da branch da entrega, que o agente
        poderia ter editado). Ausente ou inválida: política fechada."""
        ...

    async def estado_dos_checks(self, repositorio: str, sha: str) -> EstadoDosChecks: ...

    async def numero_do_pr(self, repositorio: str, branch: str) -> int | None: ...


class EscritaDeRevisao(Protocol):
    async def check_run(
        self,
        repositorio: str,
        head_sha: str,
        nome: str,
        achados: Sequence[Achado],
        resumo: str,
        chave: str,
    ) -> str: ...

    async def marcar_pr_pronto(self, repositorio: str, numero: int, chave: str) -> str: ...

    async def mesclar_pr(self, repositorio: str, numero: int, sha: str, chave: str) -> str:
        """Auto-merge. Só o workflow chama, e só quando a política e o dono permitem."""
        ...


class ClienteDeRevisao(Protocol):
    """Chamadas cruas de escrita no GitHub; só o publicador as usa, com dry-run e idempotência."""

    async def criar_check_run(
        self,
        repositorio: str,
        head_sha: str,
        nome: str,
        conclusao: str,
        titulo: str,
        resumo: str,
        anotacoes: list[dict[str, Any]],
    ) -> None: ...

    async def marcar_pr_pronto(self, repositorio: str, numero: int) -> None: ...

    async def mesclar_pr(self, repositorio: str, numero: int, sha: str) -> None: ...
