"""Skills da organização (seção 6.4.1): procedimentos com divulgação progressiva.

No contexto do agente entram só nome e descrição; o corpo só carrega quando a tarefa pede. O
conteúdo vem do repositório (não confiável), então é dado, com tetos e nome validado.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from forja.domain.artefatos import linha_unica
from forja.domain.erros import ErroDeDominio

NOME_DE_SKILL = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
MAX_CORPO = 8_000
MAX_DESCRICAO = 300


class SkillInvalida(ErroDeDominio):
    """SKILL.md fora do formato (frontmatter com name e description) ou acima dos tetos."""


@dataclass(frozen=True, slots=True)
class Skill:
    nome: str
    descricao: str
    corpo: str

    def __post_init__(self) -> None:
        if NOME_DE_SKILL.fullmatch(self.nome) is None:
            raise SkillInvalida(f"nome de skill inválido: {self.nome[:40]!r}")
        if not self.descricao.strip() or len(self.descricao) > MAX_DESCRICAO:
            raise SkillInvalida("descrição vazia ou longa demais")
        if len(self.corpo) > MAX_CORPO:
            raise SkillInvalida("corpo acima do teto")


def ler_skill(texto: str, nome_esperado: str) -> Skill:
    """Lê `---\\nname: x\\ndescription: y\\n---\\ncorpo`; o nome precisa ser o da pasta."""
    if not texto.startswith("---\n"):
        raise SkillInvalida("SKILL.md sem frontmatter")
    cabecalho, separador, corpo = texto[4:].partition("\n---")
    if not separador:
        raise SkillInvalida("frontmatter sem fechamento")
    campos: dict[str, str] = {}
    for linha in cabecalho.splitlines():
        chave, dois_pontos, valor = linha.partition(":")
        if dois_pontos:
            campos[chave.strip()] = valor.strip()
    if campos.get("name") != nome_esperado:
        raise SkillInvalida("name do frontmatter difere do nome da pasta")
    return Skill(
        nome_esperado, linha_unica(campos.get("description", ""), MAX_DESCRICAO), corpo.strip()
    )


def catalogo_para_prompt(skills: list[Skill]) -> str:
    """Só nome e descrição: o corpo carrega sob demanda (ferramenta `skill`)."""
    return "\n".join(f"- {s.nome}: {s.descricao}" for s in skills)
