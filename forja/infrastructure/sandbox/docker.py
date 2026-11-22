"""Sandbox sobre Docker rootless: um container efêmero por sessão, só com o worktree montado.

A execução real (Docker) é exercitada no CI; os testes unitários usam um CliDocker falso.
"""

from __future__ import annotations

import asyncio
import os
import re
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
USUARIO_PADRAO = "10001:10001"


def usuario_efetivo(cfg: ConfigDocker) -> str:
    """Usuário sem root do container. O worktree pertence ao processo; o container precisa
    escrever nele sem relaxar permissão (um runner Linux tem uid 1001, não 10001)."""
    if cfg.usuario:
        m = re.fullmatch(r"([0-9]+):([0-9]+)", cfg.usuario)
        if m is None or int(m[1]) == 0 or int(m[2]) == 0:
            raise SandboxError(
                f"usuario do sandbox deve ser uid:gid numerico sem root: {cfg.usuario!r}"
            )
        return cfg.usuario
    uid, gid = os.getuid(), os.getgid()
    return f"{uid}:{gid}" if uid != 0 and gid != 0 else USUARIO_PADRAO


def _entregar_worktree(worktree: Path, usuario: str) -> None:
    """Só quando o processo é root: o worktree passa ao usuário sem root do container."""
    if os.getuid() != 0:
        return
    uid, gid = (int(x) for x in usuario.split(":"))
    # lchown: o worktree é conteúdo não confiável; symlink nunca é seguido para fora dele.
    for raiz, dirs, arquivos in os.walk(worktree):
        for nome in (raiz, *(os.path.join(raiz, n) for n in (*dirs, *arquivos))):
            os.lchown(nome, uid, gid)


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
    # Vazio: o uid:gid do dono do worktree (o do processo, se não for root); com o processo
    # em root, cai em USUARIO_PADRAO e o worktree é entregue a ele. Nunca roda como root.
    usuario: str = ""
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
        "--user", usuario_efetivo(cfg),
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
            _entregar_worktree(worktree, usuario_efetivo(self._cfg))
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
