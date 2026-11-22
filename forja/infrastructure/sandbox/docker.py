"""Sandbox sobre Docker rootless: um container efêmero por sessão, só com o worktree montado.

A execução real (Docker) é exercitada no CI; os testes unitários usam um CliDocker falso.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from forja.application.portas.sandbox import (
    EspecSandbox,
    ResultadoComando,
    SandboxAtivo,
    SandboxError,
)
from forja.infrastructure.sandbox.proxy_egress import ambiente_proxy
from forja.infrastructure.sandbox.worktree import GerenciadorWorktree

DIR_CONTAINER = "/workspace"


class CliDocker(Protocol):
    async def __call__(self, *args: str, timeout_s: float = 60.0) -> ResultadoComando: ...


async def docker_real(*args: str, timeout_s: float = 60.0) -> ResultadoComando:
    proc = await asyncio.create_subprocess_exec(
        "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout_s)
    except TimeoutError:
        proc.kill()
        raise SandboxError(f"docker {args[0]} excedeu {timeout_s}s") from None
    return ResultadoComando(proc.returncode or 0, out.decode(), err.decode())


@dataclass(frozen=True)
class ConfigDocker:
    imagem: str = "forja-sandbox:latest"
    rede_interna: str = "forja-sandbox-net"
    url_proxy: str = "http://forja-egress-proxy:3128"
    usuario: str = "10001:10001"
    memoria: str = "2g"
    cpus: str = "2"
    pids: int = 512


@dataclass(frozen=True)
class _Ativo:
    sessao_id: str
    worktree: Path
    _docker: CliDocker
    _container: str

    async def executar(self, comando: list[str], timeout_s: float = 60.0) -> ResultadoComando:
        return await self._docker(
            "exec", "-w", DIR_CONTAINER, self._container, *comando, timeout_s=timeout_s
        )


def nome_container(sessao_id: str) -> str:
    return f"forja-sbx-{sessao_id}"


def argumentos_run(spec: EspecSandbox, worktree: Path, cfg: ConfigDocker) -> list[str]:
    """Monta o `docker run`. O ambiente do host nunca é herdado."""
    env = {**ambiente_proxy(cfg.url_proxy), **spec.ambiente_injetado}
    args = [
        "run", "-d", "--rm",
        "--name", nome_container(spec.sessao_id),
        "--label", f"forja.sessao={spec.sessao_id}",
        "--user", cfg.usuario,
        "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--network", cfg.rede_interna,
        "--memory", cfg.memoria, "--cpus", cfg.cpus, "--pids-limit", str(cfg.pids),
        "-v", f"{worktree}:{DIR_CONTAINER}:rw",
        "-w", DIR_CONTAINER,
    ]  # fmt: skip
    for chave, valor in env.items():
        args += ["-e", f"{chave}={valor}"]
    return [*args, cfg.imagem, "sleep", "infinity"]


class DockerSandbox:
    def __init__(
        self,
        worktrees: GerenciadorWorktree,
        repos: dict[str, Path] | None = None,
        cfg: ConfigDocker = ConfigDocker(),
        docker: CliDocker = docker_real,
    ) -> None:
        self._wt = worktrees
        self._cfg = cfg
        self._docker = docker
        self._repos: dict[str, Path] = {}
        self._origem = repos or {}

    async def criar(self, spec: EspecSandbox) -> SandboxAtivo:
        repo = self._origem.get(spec.repo_url, Path(spec.repo_url))
        worktree = await self._wt.criar(spec.sessao_id, repo, spec.ref)
        self._repos[spec.sessao_id] = repo
        try:
            res = await self._docker(*argumentos_run(spec, worktree, self._cfg))
            if res.codigo_saida != 0:
                raise SandboxError(f"docker run falhou: {res.stderr.strip()}")
        except BaseException:
            await self.destruir(spec.sessao_id)
            raise
        return _Ativo(spec.sessao_id, worktree, self._docker, nome_container(spec.sessao_id))

    async def destruir(self, sessao_id: str) -> None:
        await self._docker("rm", "-f", nome_container(sessao_id))
        repo = self._repos.pop(sessao_id, None)
        if repo is not None:
            await self._wt.remover(sessao_id, repo)
