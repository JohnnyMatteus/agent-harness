"""Git do worktree executado no host, pelo workflow. O worktree é conteúdo não confiável:
hooks e fsmonitor desligados, identidade fixa, e o agente nunca roda git (ADR 0036)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from forja.application.portas.sandbox import SandboxError
from forja.domain.artefatos import caminho_relativo_seguro
from forja.domain.guardrails import MudancaDeArquivo, eh_arquivo_de_teste

# Lixo de execução de testes (caches, bytecode) nunca entra num commit nem conta como mudança.
EXCLUDES = Path(__file__).with_name("git_excludes.txt")
OPCOES_SEGURAS = [
    "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
    "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false",
    "-c", f"core.excludesFile={EXCLUDES}",
]  # fmt: skip
IDENTIDADE = {
    "GIT_AUTHOR_NAME": "Forja",
    "GIT_AUTHOR_EMAIL": "forja@users.noreply.github.com",
    "GIT_COMMITTER_NAME": "Forja",
    "GIT_COMMITTER_EMAIL": "forja@users.noreply.github.com",
}
TETO_DE_ARQUIVO = 200_000


async def git(
    worktree: Path, *args: str, ambiente: dict[str, str] | None = None, entrada: bytes | None = None
) -> bytes:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(worktree),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        **IDENTIDADE,
        **(ambiente or {}),
    }
    proc = await asyncio.create_subprocess_exec(
        "git", *OPCOES_SEGURAS, "-C", str(worktree), *args,
        stdin=asyncio.subprocess.PIPE if entrada is not None else None,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
    )  # fmt: skip
    saida, erro = await proc.communicate(entrada)
    if proc.returncode != 0:
        raise SandboxError(f"git {args[0]} falhou: {erro.decode(errors='replace').strip()[:300]}")
    return saida


class AreaGit:
    async def ler(self, worktree: Path, caminho: str) -> str | None:
        alvo = worktree / caminho_relativo_seguro(caminho)
        if alvo.is_symlink() or not alvo.is_file():
            return None
        if alvo.stat().st_size > TETO_DE_ARQUIVO:
            raise SandboxError(f"{caminho} acima do teto de tamanho")
        return alvo.read_text(errors="replace")

    async def escrever(self, worktree: Path, caminho: str, conteudo: str) -> None:
        alvo = worktree / caminho_relativo_seguro(caminho)
        for pai in [alvo.parent, *alvo.parent.parents]:
            if pai == worktree:
                break
            if pai.is_symlink():
                raise SandboxError("diretório de destino é link simbólico")
        alvo.parent.mkdir(parents=True, exist_ok=True)
        if alvo.is_symlink():
            raise SandboxError("destino é link simbólico")
        alvo.write_text(conteudo)

    async def head(self, worktree: Path) -> str:
        return (await git(worktree, "rev-parse", "HEAD")).decode().strip()

    async def garantir_branch(self, worktree: Path, branch: str) -> None:
        await git(worktree, "checkout", "-q", "-B", branch)

    async def mudancas(self, worktree: Path, base: str) -> list[MudancaDeArquivo]:
        await git(worktree, "add", "-A")
        bruto = await git(worktree, "diff", "--cached", "--raw", "-z", "--no-renames", base)
        campos = bruto.decode(errors="replace").split("\0")
        mudancas: list[MudancaDeArquivo] = []
        for cabecalho, caminho in zip(campos[0::2], campos[1::2], strict=False):
            partes = cabecalho.lstrip(":").split()
            if len(partes) < 5:
                continue
            modo_antigo, modo_novo, status = partes[0], partes[1], partes[4][0]
            modo = modo_novo if status != "D" else modo_antigo
            mudancas.append(MudancaDeArquivo(caminho, status, modo))
        return mudancas

    async def descartar(self, worktree: Path, base: str) -> None:
        await git(worktree, "reset", "-q", "--hard", base)
        await git(worktree, "clean", "-fdxq")

    async def commitar(self, worktree: Path, mensagem: str) -> str | None:
        await git(worktree, "add", "-A")
        if not (await git(worktree, "status", "--porcelain")).strip():
            return None
        await git(worktree, "commit", "-q", "-F", "-", entrada=mensagem.encode())
        return await self.head(worktree)

    async def log_recente(self, worktree: Path, quantos: int) -> str:
        try:
            return (await git(worktree, "log", f"-{max(1, quantos)}", "--format=%h %s")).decode()
        except SandboxError:
            return ""

    async def arquivos_de_teste_e_links(
        self, worktree: Path
    ) -> tuple[frozenset[str], frozenset[str]]:
        raiz = worktree.resolve()
        testes: set[str] = set()
        links: set[str] = set()
        for pasta, dirs, arquivos in os.walk(worktree):
            dirs[:] = [d for d in dirs if d != ".git"]
            for nome in [*dirs, *arquivos]:
                caminho = Path(pasta) / nome
                relativo = str(caminho.relative_to(worktree))
                if caminho.is_symlink():
                    if not caminho.resolve().is_relative_to(raiz):
                        raise SandboxError(
                            f"link simbólico aponta para fora do worktree: {relativo}"
                        )
                    links.add(relativo)
                elif nome in arquivos and eh_arquivo_de_teste(relativo):
                    testes.add(relativo)
        return frozenset(testes), frozenset(links)
