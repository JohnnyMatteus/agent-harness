from __future__ import annotations

from forja.application.portas.skills import FonteDeSkills
from forja.domain.skills import Skill, SkillInvalida, ler_skill


class CatalogoDeSkills:
    """Skills do repositório-alvo sobre as padrão da Forja; uma skill inválida é ignorada, nunca
    carregada pela metade. O repositório pode sobrescrever o nome de uma padrão."""

    def __init__(self, padrao: FonteDeSkills, do_repositorio: FonteDeSkills | None = None) -> None:
        self._padrao = padrao
        self._repo = do_repositorio

    async def listar(self, repositorio: str) -> list[Skill]:
        por_nome: dict[str, Skill] = {}
        for fonte in (self._padrao, self._repo):
            if fonte is None:
                continue
            for nome in await fonte.nomes(repositorio):
                texto = await fonte.ler(repositorio, nome)
                if texto is None:
                    continue
                try:
                    por_nome[nome] = ler_skill(texto, nome)
                except SkillInvalida:
                    continue
        return [por_nome[n] for n in sorted(por_nome)]

    async def carregar(self, repositorio: str, nome: str) -> str:
        """Corpo de uma skill do catálogo. Nome fora do catálogo é recusado (nada de caminho)."""
        for skill in await self.listar(repositorio):
            if skill.nome == nome:
                return skill.corpo
        raise SkillInvalida(f"skill desconhecida: {nome[:40]!r}")
