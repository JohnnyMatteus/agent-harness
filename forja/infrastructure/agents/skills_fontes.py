from __future__ import annotations

from collections.abc import Awaitable, Callable
from importlib import resources

from forja.domain.skills import NOME_DE_SKILL

LerArquivo = Callable[[str, str, str], Awaitable[str | None]]
BranchPadrao = Callable[[str], Awaitable[str]]


class SkillsPadrao:
    """As skills que a Forja traz (`forja/infrastructure/agents/skills/`)."""

    async def nomes(self, repositorio: str) -> list[str]:
        raiz = resources.files("forja.infrastructure.agents").joinpath("skills")
        return sorted(p.name for p in raiz.iterdir() if p.is_dir())

    async def ler(self, repositorio: str, nome: str) -> str | None:
        if NOME_DE_SKILL.fullmatch(nome) is None:
            return None
        raiz = resources.files("forja.infrastructure.agents").joinpath("skills", nome, "SKILL.md")
        return raiz.read_text("utf-8") if raiz.is_file() else None


class SkillsDoRepositorio:
    """`.forja/skills/<nome>/SKILL.md` na branch PADRÃO do repositório-alvo (versionadas pelo
    dono; o agente não escreve em `.forja/`). Os nomes vêm de `.forja/skills.txt`: a API de
    conteúdo do GitHub é lida por arquivo, e uma listagem de diretório seria mais uma superfície."""

    def __init__(self, ler_arquivo: LerArquivo, branch_padrao: BranchPadrao) -> None:
        self._ler = ler_arquivo
        self._padrao = branch_padrao

    async def nomes(self, repositorio: str) -> list[str]:
        texto = await self._ler(repositorio, await self._padrao(repositorio), ".forja/skills.txt")
        if texto is None:
            return []
        candidatos = [linha.strip() for linha in texto.splitlines()]
        return [n for n in candidatos if NOME_DE_SKILL.fullmatch(n)][:30]

    async def ler(self, repositorio: str, nome: str) -> str | None:
        if NOME_DE_SKILL.fullmatch(nome) is None:
            return None
        branch = await self._padrao(repositorio)
        return await self._ler(repositorio, branch, f".forja/skills/{nome}/SKILL.md")
