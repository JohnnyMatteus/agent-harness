"""Varredura de um checkout: o conteúdo do repositório é não confiável.

Não segue symlink, recusa segredo, binário, arquivo grande e caminho que escapa da raiz.
Recusas são contadas por motivo; o conteúdo recusado nunca é devolvido nem logado.
"""

from __future__ import annotations

import errno
import hashlib
import os
import re
import stat
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from forja.application.portas.knowledge import ArquivoFonte, Varredura
from forja.infrastructure.knowledge.chunker import EXTENSOES_SUPORTADAS

DIRETORIOS_IGNORADOS = frozenset(
    {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", ".mypy_cache"}
)
NOMES_DE_SEGREDO = re.compile(
    r"(^\.env(\..*)?$|^id_(rsa|dsa|ecdsa|ed25519)$|\.(pem|key|p12|pfx|jks)$|^\.netrc$|^credentials(\..*)?$)",
    re.IGNORECASE,
)
# Padrões de alta precisão; um arquivo com qualquer um deles é recusado inteiro.
PADROES_DE_SEGREDO = tuple(
    re.compile(p)
    for p in (
        r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----",
        r"\bAKIA[0-9A-Z]{16}\b",
        r"\bgh[pousr]_[A-Za-z0-9]{36,}\b",
        r"\bgithub_pat_[A-Za-z0-9_]{50,}\b",
        r"\bsk-ant-[A-Za-z0-9_-]{20,}\b",
        r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b",
        r"\bAIza[0-9A-Za-z_-]{35}\b",
        r"(?i)\b(?:password|passwd|secret|api[_-]?key|token)\b\s*[:=]\s*[\"'][^\"'\s]{12,}[\"']",
    )
)


def contem_segredo(texto: str) -> bool:
    return any(p.search(texto) for p in PADROES_DE_SEGREDO)


class VarreduraDeDiretorio:
    def __init__(
        self,
        raiz: Path,
        commit: str,
        *,
        max_bytes_por_arquivo: int = 256 * 1024,
        max_arquivos: int = 5000,
        max_bytes_total: int = 64 * 1024 * 1024,
        extensoes: Iterable[str] = EXTENSOES_SUPORTADAS,
    ) -> None:
        self._raiz = raiz.resolve()
        self._commit = commit
        self._max_arquivo = max_bytes_por_arquivo
        self._max_arquivos = max_arquivos
        self._max_total = max_bytes_total
        self._extensoes = frozenset(extensoes)

    def varrer(self) -> Varredura:
        aceitos: list[ArquivoFonte] = []
        nao_lidos: list[str] = []
        recusados: dict[str, int] = {}
        total = 0

        def recusar(motivo: str) -> None:
            recusados[motivo] = recusados.get(motivo, 0) + 1

        def erro_de_diretorio(erro: OSError) -> None:
            nao_lidos.append(self._relativo(Path(str(erro.filename or self._raiz))))

        for diretorio, subdiretorios, nomes in os.walk(
            self._raiz, followlinks=False, onerror=erro_de_diretorio
        ):
            subdiretorios[:] = sorted(
                d
                for d in subdiretorios
                if d not in DIRETORIOS_IGNORADOS and not (Path(diretorio) / d).is_symlink()
            )
            for nome in sorted(nomes):
                caminho = Path(diretorio) / nome
                motivo, conteudo = self._ler(caminho, nome)
                if motivo == "ilegivel":
                    nao_lidos.append(self._relativo(caminho))
                    recusar(motivo)
                    continue
                if motivo:
                    recusar(motivo)
                    continue
                assert conteudo is not None
                if len(aceitos) >= self._max_arquivos or total + len(conteudo) > self._max_total:
                    recusar("limite_total")
                    continue
                total += len(conteudo)
                relativo = self._relativo(caminho)
                aceitos.append(
                    ArquivoFonte(
                        relativo, conteudo.decode("utf-8"), hashlib.sha256(conteudo).hexdigest()
                    )
                )
        return Varredura(self._commit, tuple(aceitos), recusados, tuple(nao_lidos))

    def _relativo(self, caminho: Path) -> str:
        try:
            partes = caminho.relative_to(self._raiz).parts
        except ValueError:
            return "."
        return PurePosixPath(*partes).as_posix() if partes else "."

    def _ler(self, caminho: Path, nome: str) -> tuple[str | None, bytes | None]:
        if NOMES_DE_SEGREDO.search(nome):
            return "segredo", None
        if caminho.suffix.lower() not in self._extensoes:
            return "extensao", None
        try:
            # O_NOFOLLOW fecha a janela entre o teste de symlink e a abertura; O_NONBLOCK evita
            # que a abertura de um FIFO sem escritor bloqueie para sempre.
            descritor = os.open(caminho, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError as erro:
            return ("symlink" if erro.errno == errno.ELOOP else "ilegivel"), None
        try:
            info = os.fstat(descritor)
            if not stat.S_ISREG(info.st_mode):
                return "nao_regular", None
            if info.st_size > self._max_arquivo:
                return "grande", None
            with os.fdopen(descritor, "rb", closefd=False) as arquivo:
                conteudo = arquivo.read(self._max_arquivo + 1)
        finally:
            os.close(descritor)
        if len(conteudo) > self._max_arquivo:
            return "grande", None
        if b"\x00" in conteudo:
            return "binario", None
        try:
            texto = conteudo.decode("utf-8")
        except UnicodeDecodeError:
            return "nao_utf8", None
        if contem_segredo(texto):
            return "segredo", None
        return None, conteudo
