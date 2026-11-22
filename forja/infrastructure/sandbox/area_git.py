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
import contextlib
import os
import shutil
import stat
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


def _recusar_erro(erro: OSError) -> None:
    """`os.walk` engole erro de listagem por padrão; numa árvore hostil isso esconde o que não
    pôde ser lido (um `chmod 300` basta). Aqui a falha é a resposta."""
    raise SandboxError(f"diretório ilegível no worktree: {getattr(erro, 'filename', '?')}")


def varrer_git_aninhado(worktree: Path) -> list[Path]:
    """`.git` em qualquer subdiretório (repositório falso, gitlink): o git do host não pode
    descer neles. Não segue links simbólicos e falha se algum diretório não puder ser lido."""
    achados: list[Path] = []
    for pasta, dirs, arquivos in os.walk(worktree, followlinks=False, onerror=_recusar_erro):
        relativo = Path(pasta).relative_to(worktree)
        for nome in [*dirs, *arquivos]:
            if nome.lower() == ".git" and relativo != Path("."):
                achados.append(Path(pasta) / nome)
    return achados


def _ilegiveis(worktree: Path) -> list[str]:
    achados: list[str] = []
    for _ in os.walk(
        worktree, followlinks=False, onerror=lambda e: achados.append(str(e.filename))
    ):
        pass
    return achados


def reabrir_permissoes(worktree: Path) -> None:
    """Só no descarte: devolve leitura aos diretórios que o agente fechou, para poder limpá-los."""
    for _ in range(MAX_PASSADAS_DE_PERMISSAO):
        ilegiveis = _ilegiveis(worktree)
        if not ilegiveis:
            return
        for caminho in ilegiveis:
            with contextlib.suppress(OSError):
                os.chmod(caminho, 0o700)
    raise SandboxError("não foi possível reabrir as permissões do worktree")


MAX_PASSADAS_DE_PERMISSAO = 20


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
    """Abre `relativo` dentro do worktree sem seguir link simbólico em NENHUM componente, sem
    bloquear (um FIFO no lugar do arquivo travaria o worker) e só se for arquivo regular."""
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
        arquivo = os.open(partes[-1], flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o644, dir_fd=fd)
        if not stat.S_ISREG(os.fstat(arquivo).st_mode):  # fifo, socket, dispositivo, diretório
            os.close(arquivo)
            raise OSError("não é arquivo regular")
        return arquivo
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
            raise SandboxError(
                f"{caminho}: link simbólico no caminho ou não é arquivo regular"
            ) from None
        with os.fdopen(fd, "rb") as f:
            if os.fstat(f.fileno()).st_size > TETO_DE_ARQUIVO:
                raise SandboxError(f"{caminho} acima do teto de tamanho")
            return f.read().decode(errors="replace")

    async def escrever(self, worktree: Path, caminho: str, conteudo: str) -> None:
        relativo = caminho_relativo_seguro(caminho)
        try:
            fd = _abrir_sem_seguir(
                worktree, relativo, os.O_WRONLY | os.O_CREAT, criar_diretorios=True
            )
        except OSError:
            raise SandboxError(
                f"{caminho}: link, fifo ou destino que não é arquivo regular"
            ) from None
        with os.fdopen(fd, "w") as f:
            f.truncate(0)  # só depois de confirmar que é arquivo regular
            f.write(conteudo)

    async def head(self, worktree: Path) -> str:
        return (await git(worktree, "rev-parse", "HEAD")).decode().strip()

    async def destacar(self, worktree: Path) -> None:
        await git(worktree, "checkout", "-q", "--detach")

    async def _recusar_gitlink(self, worktree: Path, raiz: str) -> None:
        """Gitlink (modo 160000) na árvore de `raiz`: lido dos objetos, sem depender de listar o
        worktree (que o agente pode ter deixado ilegível)."""
        arvore = await git(worktree, "ls-tree", "-r", "-z", raiz)
        for entrada in arvore.decode(errors="replace").split("\0"):
            if entrada.startswith("160000 "):
                raise SandboxError(
                    f"gitlink (submódulo) não suportado: {entrada.split(chr(9))[-1]}"
                )

    async def mudancas(self, worktree: Path, base: str) -> list[MudancaDeArquivo]:
        await self._recusar_gitlink(worktree, base)
        aninhados = varrer_git_aninhado(worktree)
        if aninhados:
            raise SandboxError(f"repositório git aninhado: {aninhados[0].relative_to(worktree)}")
        await git(worktree, "add", "-A")
        bruto = await git(
            worktree, "diff", "--cached", "--raw", "-z", "--no-renames", "--no-ext-diff",
            "--no-textconv", "--ignore-submodules=all", base,
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
        reabrir_permissoes(worktree)
        for aninhado in varrer_git_aninhado(worktree):  # remove o que o git não deve percorrer
            if aninhado.is_dir() and not aninhado.is_symlink():
                shutil.rmtree(aninhado, ignore_errors=True)
            else:
                aninhado.unlink(missing_ok=True)
        await git(worktree, "reset", "-q", "--hard", base)
        await git(worktree, "clean", "-ffdxq")

    async def commitar(self, worktree: Path, mensagem: str) -> str | None:
        await self._recusar_gitlink(worktree, "HEAD")
        aninhados = varrer_git_aninhado(worktree)
        if aninhados:
            raise SandboxError(f"repositório git aninhado: {aninhados[0].relative_to(worktree)}")
        await git(worktree, "add", "-A")
        if not (await git(worktree, "status", "--porcelain", "--ignore-submodules=all")).strip():
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
        for pasta, dirs, arquivos in os.walk(worktree, followlinks=False, onerror=_recusar_erro):
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
