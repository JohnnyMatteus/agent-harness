"""Artefatos do SDLC (intent.md, spec.md, plan.md): objetos de valor validados e renderizados
por código. O modelo só propõe dados; nunca escreve o arquivo nem escolhe o caminho."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from forja.domain.erros import ErroDeDominio

_ID_DA_INTENT = re.compile(r"[0-9a-f]{16}")
_CONTROLE = re.compile("[\x00-\x1f\x7f\u2028\u2029]")
_SEGMENTO = re.compile(r"[A-Za-z0-9_.@+=,~-][A-Za-z0-9_.@+=, ~-]*")


class ArtefatoInvalido(ErroDeDominio):
    """Dado de artefato que não passa na validação (vem de um modelo ou de um humano)."""


class NomeDeArtefato(StrEnum):
    INTENT = "intent.md"
    SPEC = "spec.md"
    PLAN = "plan.md"
    FEATURE_LIST = "feature_list.json"
    PROGRESS = "progress.md"
    INIT = "init.sh"
    CONTRATO = "sprint-contract.json"
    REVIEW = "review.md"


def intent_id_valido(intent_id: str) -> bool:
    return _ID_DA_INTENT.fullmatch(intent_id) is not None


def caminho_do_artefato(intent_id: str, nome: NomeDeArtefato | str) -> str:
    """`.forja/<intent-id>/<nome>`: o único lugar onde artefatos são escritos (seção 5.2)."""
    if not intent_id_valido(intent_id):
        raise ArtefatoInvalido("id de intent inválido")
    try:
        artefato = NomeDeArtefato(nome)
    except ValueError:
        raise ArtefatoInvalido(f"artefato desconhecido: {str(nome)[:40]!r}") from None
    return f".forja/{intent_id}/{artefato.value}"


def caminho_relativo_seguro(caminho: str) -> str:
    """Caminho dentro do repositório: relativo, sem `..`, sem `.git`, sem controle ou barra
    invertida. Vale para qualquer caminho que venha de um modelo ou de um arquivo do repo."""
    if not caminho or len(caminho) > 300 or _CONTROLE.search(caminho) or "\\" in caminho:
        raise ArtefatoInvalido("caminho vazio, longo ou com caractere de controle")
    if caminho.startswith(("/", "~")) or caminho.endswith("/"):
        raise ArtefatoInvalido("caminho deve ser relativo a um arquivo")
    partes = caminho.split("/")
    if any(p in ("", ".", "..") or not _SEGMENTO.fullmatch(p) for p in partes):
        raise ArtefatoInvalido("segmento de caminho inválido")
    if partes[0].lower() == ".git" or any(p.lower() == ".git" for p in partes):
        raise ArtefatoInvalido("caminho dentro de .git")
    return caminho


def linha_unica(texto: str, limite: int = 500) -> str:
    """Item de lista em uma linha só: texto de modelo não consegue abrir título ou bloco."""
    return _CONTROLE.sub(" ", texto).replace("```", "'''").strip()[:limite]


TETO_DE_ARTEFATO = 200_000


def sanear_mensagem_de_commit(mensagem: str) -> str:
    """Assunto numa linha só; o corpo (trailers Intent-Id, Run-Id...) mantém uma linha por item,
    cada uma saneada. Achatar tudo em uma linha desfaria os trailers."""
    assunto, *corpo = mensagem.split("\n")  # splitlines() também quebra em U+2028 e afins
    linhas = [linha_unica(assunto, 100)]
    if corpo:
        linhas += [linha_unica(c, 200) for c in corpo[:30]]
    return "\n".join(linhas)


@dataclass(frozen=True, slots=True)
class Fonte:
    """Citação obrigatória (seção 6.3): de onde vem uma afirmação do RAG."""

    id: str
    caminho: str
    commit: str


@dataclass(frozen=True, slots=True)
class IntentMd:
    problema: str
    criterios_de_sucesso: tuple[str, ...]
    origem: str
    url: str | None = None

    def renderizar(self) -> str:
        linhas = ["# intent", "", "## Problema", "", linha_unica(self.problema, 2000), ""]
        linhas += ["## Origem", "", linha_unica(self.origem, 300)]
        if self.url:
            linhas.append(linha_unica(self.url, 300))
        linhas += ["", "## Critérios de sucesso declarados", ""]
        linhas += [f"- {linha_unica(c)}" for c in self.criterios_de_sucesso] or ["- (nenhum)"]
        return "\n".join(linhas) + "\n"


@dataclass(frozen=True, slots=True)
class Cenario:
    titulo: str
    passos: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Spec:
    requisitos: tuple[str, ...]
    restricoes: tuple[str, ...]
    cenarios: tuple[Cenario, ...]
    adrs_afetados: tuple[str, ...]
    pontos_em_aberto: tuple[str, ...]
    fontes: tuple[Fonte, ...] = ()

    def renderizar(self) -> str:
        def lista(itens: tuple[str, ...]) -> list[str]:
            return [f"- {linha_unica(i)}" for i in itens] or ["- (nenhum)"]

        linhas = ["# spec", "", "## Requisitos", "", *lista(self.requisitos), ""]
        linhas += ["## Restrições", "", *lista(self.restricoes), "", "## Critérios de aceite", ""]
        for c in self.cenarios:
            linhas += ["```gherkin", f"Cenário: {linha_unica(c.titulo, 200)}"]
            linhas += [f"  {linha_unica(p)}" for p in c.passos]
            linhas += ["```", ""]
        linhas += ["## ADRs afetados", "", *lista(self.adrs_afetados), ""]
        linhas += ["## Pontos em aberto", "", *lista(self.pontos_em_aberto), ""]
        linhas += ["## Fontes", ""]
        linhas += [f"- {f.caminho}@{f.commit[:12]}" for f in self.fontes] or ["- (sem fontes)"]
        return "\n".join(linhas) + "\n"


@dataclass(frozen=True, slots=True)
class PassoDoPlano:
    arquivo: str
    mudanca: str
    testes: tuple[str, ...]

    def __post_init__(self) -> None:
        caminho_relativo_seguro(self.arquivo)


@dataclass(frozen=True, slots=True)
class Plano:
    passos: tuple[PassoDoPlano, ...]

    def __post_init__(self) -> None:
        if not self.passos:
            raise ArtefatoInvalido("plano sem passos")

    @property
    def arquivos(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(p.arquivo for p in self.passos))

    def renderizar(self) -> str:
        linhas = ["# plan", "", "## Passos (em ordem)", ""]
        for i, p in enumerate(self.passos, 1):
            linhas += [f"{i}. `{p.arquivo}`: {linha_unica(p.mudanca)}"]
            linhas += [f"   - teste: {linha_unica(t)}" for t in p.testes]
        return "\n".join(linhas) + "\n"
