"""Git do worktree executado no host, pelo workflow. O worktree é gravável pelo container, então
é conteúdo hostil: nada que ele contém pode virar configuração do git do host (ADR 0040).

- `GIT_DIR` e `GIT_WORK_TREE` explícitos, com o gitdir resolvido na criação e guardado fora do
  worktree; o ponteiro `.git` do worktree é só conferido e uma divergência recusa a operação;
- HOME vazio fora do worktree, sem config global nem de sistema, hooks e fsmonitor desligados,
  diff sem programa externo nem textconv;
- `.git` aninhado e gitlink são recusados antes de qualquer git que desça neles;
- leitura e escrita de arquivo abrem cada componente sem seguir link simbólico.

Quem chama deve ter parado o container (todos os processos) antes de usar a área (TOCTOU).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path

from forja.application.portas.sandbox import SandboxError
from forja.domain.artefatos import caminho_relativo_seguro
from forja.domain.guardrails import MudancaDeArquivo, eh_arquivo_de_teste
from forja.infrastructure.sandbox.worktree import gitdir_registrado

# Lixo de execução de testes (caches, bytecode) nunca entra num commit nem conta como mudança.
EXCLUDES = Path(__file__).with_name("git_excludes.txt")
OPCOES_SEGURAS = [
    "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
    "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false",
    "-c", f"core.excludesFile={EXCLUDES}", "-c", "core.attributesFile=/dev/null",
    "-c", "protocol.ext.allow=never",
]  # fmt: skip
IDENTIDADE = {
    "GIT_AUTHOR_NAME": "Forja",
    "GIT_AUTHOR_EMAIL": "forja@users.noreply.github.com",
    "GIT_COMMITTER_NAME": "Forja",
    "GIT_COMMITTER_EMAIL": "forja@users.noreply.github.com",
}
TETO_DE_ARQUIVO = 200_000
_HOME_VAZIO = Path(tempfile.mkdtemp(prefix="forja-git-home-"))


def verificar_ponteiro(worktree: Path, ponteiro: str) -> None:
    """O `.git` da raiz é o arquivo registrado na criação; qualquer outra coisa é adulteração."""
    try:
        fd = _abrir_sem_seguir(worktree, ".git", os.O_RDONLY)
        with os.fdopen(fd) as f:
            conteudo = f.read(4096)
    except OSError:
        raise SandboxError("ponteiro .git ausente, diretório ou link simbólico") from None
    if conteudo.strip() != ponteiro:
        raise SandboxError("ponteiro .git do worktree foi alterado")


def varrer_git_aninhado(worktree: Path) -> list[Path]:
    """`.git` em qualquer subdiretório (repositório falso, gitlink): o git do host não pode
    descer neles. Não segue links simbólicos."""
    achados: list[Path] = []
    for pasta, dirs, arquivos in os.walk(worktree, followlinks=False):
        relativo = Path(pasta).relative_to(worktree)
        for nome in [*dirs, *arquivos]:
            if nome.lower() == ".git" and relativo != Path("."):
                achados.append(Path(pasta) / nome)
    return achados


async def git(
    worktree: Path, *args: str, ambiente: dict[str, str] | None = None, entrada: bytes | None = None
) -> bytes:
    gitdir, ponteiro = gitdir_registrado(worktree)
    verificar_ponteiro(worktree, ponteiro)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(_HOME_VAZIO),
        "GIT_DIR": str(gitdir),
        "GIT_WORK_TREE": str(worktree),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        **IDENTIDADE,
        **(ambiente or {}),
    }
    proc = await asyncio.create_subprocess_exec(
        "git", *OPCOES_SEGURAS, *args,
        cwd=worktree,
        stdin=asyncio.subprocess.PIPE if entrada is not None else None,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
    )  # fmt: skip
    saida, erro = await proc.communicate(entrada)
    if proc.returncode != 0:
        raise SandboxError(f"git {args[0]} falhou: {erro.decode(errors='replace').strip()[:300]}")
    return saida


def _abrir_sem_seguir(
    worktree: Path, relativo: str, flags: int, *, criar_diretorios: bool = False
) -> int:
    """Abre `relativo` dentro do worktree sem seguir link simbólico em NENHUM componente."""
    partes = relativo.split("/")
    fd = os.open(worktree, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for parte in partes[:-1]:
            try:
                novo = os.open(parte, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                if not criar_diretorios:
                    raise
                os.mkdir(parte, 0o755, dir_fd=fd)
                novo = os.open(parte, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = novo
        return os.open(partes[-1], flags | os.O_NOFOLLOW, 0o644, dir_fd=fd)
    finally:
        os.close(fd)


class AreaGit:
    async def ler(self, worktree: Path, caminho: str) -> str | None:
        relativo = caminho_relativo_seguro(caminho)
        try:
            fd = _abrir_sem_seguir(worktree, relativo, os.O_RDONLY)
        except FileNotFoundError:
            return None
        except OSError:
            raise SandboxError(f"{caminho}: link simbólico no caminho") from None
        with os.fdopen(fd, "rb") as f:
            if os.fstat(f.fileno()).st_size > TETO_DE_ARQUIVO:
                raise SandboxError(f"{caminho} acima do teto de tamanho")
            return f.read().decode(errors="replace")

    async def escrever(self, worktree: Path, caminho: str, conteudo: str) -> None:
        relativo = caminho_relativo_seguro(caminho)
        try:
            fd = _abrir_sem_seguir(
                worktree, relativo, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, criar_diretorios=True
            )
        except OSError:
            raise SandboxError(f"{caminho}: link simbólico no caminho de escrita") from None
        with os.fdopen(fd, "w") as f:
            f.write(conteudo)

    async def head(self, worktree: Path) -> str:
        return (await git(worktree, "rev-parse", "HEAD")).decode().strip()

    async def garantir_branch(self, worktree: Path, branch: str) -> None:
        await git(worktree, "checkout", "-q", "-B", branch)

    async def mudancas(self, worktree: Path, base: str) -> list[MudancaDeArquivo]:
        aninhados = varrer_git_aninhado(worktree)
        if aninhados:
            raise SandboxError(f"repositório git aninhado: {aninhados[0].relative_to(worktree)}")
        await git(worktree, "add", "-A")
        bruto = await git(
            worktree, "diff", "--cached", "--raw", "-z", "--no-renames", "--no-ext-diff",
            "--no-textconv", base,
        )  # fmt: skip
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

    def _restaurar_ponteiro(self, worktree: Path) -> None:
        """Devolve o `.git` ao que foi registrado na criação (o container pode tê-lo trocado)."""
        _, ponteiro = gitdir_registrado(worktree)
        alvo = worktree / ".git"
        if alvo.is_symlink() or alvo.is_file():
            alvo.unlink()
        elif alvo.is_dir():
            shutil.rmtree(alvo, ignore_errors=True)
        alvo.write_text(ponteiro + "\n")

    async def descartar(self, worktree: Path, base: str) -> None:
        self._restaurar_ponteiro(worktree)
        for aninhado in varrer_git_aninhado(worktree):  # remove o que o git não deve percorrer
            if aninhado.is_dir() and not aninhado.is_symlink():
                shutil.rmtree(aninhado, ignore_errors=True)
            else:
                aninhado.unlink(missing_ok=True)
        await git(worktree, "reset", "-q", "--hard", base)
        await git(worktree, "clean", "-ffdxq")

    async def commitar(self, worktree: Path, mensagem: str) -> str | None:
        aninhados = varrer_git_aninhado(worktree)
        if aninhados:
            raise SandboxError(f"repositório git aninhado: {aninhados[0].relative_to(worktree)}")
        await git(worktree, "add", "-A")
        if not (await git(worktree, "status", "--porcelain")).strip():
            return None
        await git(worktree, "commit", "-q", "--no-verify", "-F", "-", entrada=mensagem.encode())
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
        for pasta, dirs, arquivos in os.walk(worktree, followlinks=False):
            dirs[:] = [d for d in dirs if not (d == ".git" and Path(pasta) == worktree)]
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
