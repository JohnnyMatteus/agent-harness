# pyright: basic
"""Dublês do harness: sandbox local (git worktree real, comandos no host), agentes roteirizados."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from forja.application.portas.agente import UsoModelo
from forja.application.portas.harness import (
    Avaliacao,
    PlanoInicial,
    PropostaDeContrato,
    ResultadoDeSessao,
    RevisaoDoContrato,
)
from forja.application.portas.sandbox import EspecSandbox, ResultadoComando
from forja.domain.harness import (
    LIMIARES_PROVISORIOS,
    ContratoDeSprint,
    Criterio,
    Feature,
    FeatureList,
)
from forja.infrastructure.sandbox.worktree import GerenciadorWorktree

ID = "0123456789abcdef"
REPO = "acme/loja"
BRANCH = f"forja/{ID}-corrige-login"


def teste_de(fid: str) -> tuple[str, ...]:
    return ("python", "-m", "pytest", "-q", f"tests/test_{fid}.py")


def feature(fid: str) -> Feature:
    return Feature(fid, "funcional", f"faz {fid}", ("abre", "confere"), teste_de(fid))


class AtivoLocal:
    def __init__(self, sessao_id: str, worktree: Path) -> None:
        self.sessao_id, self.worktree = sessao_id, worktree

    async def executar(self, comando: list[str], timeout_s: float = 60.0) -> ResultadoComando:
        argv = [sys.executable if comando[0] in ("python", "python3") else comando[0], *comando[1:]]
        if comando[0] == "pytest":
            argv = [sys.executable, "-m", "pytest", *comando[1:]]
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.worktree),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        r = await asyncio.to_thread(
            subprocess.run, argv, cwd=self.worktree, capture_output=True, text=True, env=env
        )
        return ResultadoComando(r.returncode, r.stdout, r.stderr)


class SandboxLocal:
    def __init__(self, raiz: Path) -> None:
        self._wt = GerenciadorWorktree(raiz)
        self.criados: list[str] = []
        self.destruidos: list[str] = []
        self._repos: dict[str, Path] = {}

    async def criar(self, spec: EspecSandbox):
        self.criados.append(spec.sessao_id)
        repo = Path(spec.repo_url)
        self._repos[spec.sessao_id] = repo
        return AtivoLocal(spec.sessao_id, await self._wt.criar(spec.sessao_id, repo))

    async def destruir(self, sessao_id: str) -> None:
        self.destruidos.append(sessao_id)
        repo = self._repos.pop(sessao_id, None)
        if repo is not None:
            await self._wt.remover(sessao_id, repo)


class InicializadorFalso:
    def __init__(self, *ids: str) -> None:
        self.ids = ids or ("f1", "f2")
        self.chamadas = 0

    async def inicializar(self, repositorio, spec_md, plano_md) -> PlanoInicial:
        self.chamadas += 1
        lista = FeatureList(
            tuple(feature(i) for i in self.ids),
            ("python", "-m", "pytest", "-q", "tests/test_smoke.py"),
        )
        return PlanoInicial(lista, (("ls", "-la"),), lista.comando_de_fumaca, UsoModelo(10, 5, 0.1))


class ExecutorFalso:
    """Escreve no worktree o que o agente escreveria com Write/Edit."""

    def __init__(self) -> None:
        self.sessoes: list[str] = []
        self.sabotagem: Callable[[Path, Feature], object] | None = None
        self.atualiza_progress = True
        self.implementa = True
        self.feedbacks: list[str] = []
        self.contextos: list[str] = []
        self.contrato_ajustes: list[list[str]] = []
        self.features_do_contrato: tuple[str, ...] | None = None
        self.atraso = 0.0

    async def propor_contrato(self, repositorio, bloco, features, ajustes) -> PropostaDeContrato:
        self.contrato_ajustes.append(list(ajustes))
        ids = self.features_do_contrato or tuple(f.id for f in features)
        contrato = ContratoDeSprint(
            bloco, ids, ("entrega",), ("roda o teste",), LIMIARES_PROVISORIOS
        )
        return PropostaDeContrato(contrato, UsoModelo(5, 2, 0.05))

    async def executar_sessao(
        self, sandbox, repositorio, intent_id, feature, contexto, feedback, politica
    ) -> ResultadoDeSessao:
        await asyncio.sleep(self.atraso)
        self.sessoes.append(feature.id)
        self.feedbacks.append(feedback)
        self.contextos.append(contexto)
        wt = sandbox.worktree
        if self.implementa:
            (wt / "src").mkdir(exist_ok=True)
            (wt / "tests").mkdir(exist_ok=True)
            (wt / "src" / f"{feature.id}.py").write_text("OK = True\n")
            (wt / "tests" / f"test_{feature.id}.py").write_text(
                f"import sys\nsys.path.insert(0, 'src')\nimport {feature.id}\n"
                f"def test_ok():\n    assert {feature.id}.OK\n"
            )
        if self.atualiza_progress:
            p = wt / ".forja" / intent_id / "progress.md"
            p.write_text(p.read_text() + f"\n- {feature.id} feito\n")
        if self.sabotagem:
            self.sabotagem(wt, feature)
        return ResultadoDeSessao(
            f"implementa {feature.id}", f"{feature.id} implementada", UsoModelo(20, 10, 0.2)
        )


class AvaliadorFalso:
    def __init__(self) -> None:
        self.acordos = [True]
        self.nota = 9
        self.pedidos = []
        self.revisoes = 0

    async def revisar_contrato(self, repositorio, contrato) -> RevisaoDoContrato:
        self.revisoes += 1
        acordo = self.acordos.pop(0) if self.acordos else True
        return RevisaoDoContrato(acordo, () if acordo else ("cubra o erro",), UsoModelo(5, 2, 0.05))

    async def avaliar(self, sandbox, repositorio, pedido) -> Avaliacao:
        self.pedidos.append(pedido)
        notas = dict.fromkeys(Criterio, self.nota)
        return Avaliacao(notas, {Criterio.FUNCIONALIDADE: "ok"}, (), UsoModelo(30, 15, 0.3))
