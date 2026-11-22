"""Guardrails determinísticos das sessões de agente (seções 5.3 e 9.2): política como código.

São funções puras. O adaptador do SDK as chama no PreToolUse (ponto de entrada de toda
ferramenta) e o worker as reaplica depois da sessão sobre o diff (`auditar_mudancas`), porque
um comando permitido (testes, scripts) também escreve arquivo e o hook não o vê.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, cast

from forja.domain.artefatos import ArtefatoInvalido, caminho_relativo_seguro

RAIZ_NO_SANDBOX = "/workspace"
FERRAMENTA_EXEC = "mcp__sandbox__exec"
PREFIXO_MEMORIA = "mcp__memoria__"
PREFIXO_SKILLS = "mcp__skills__"
LEITURA = frozenset({"Read", "Glob", "Grep"})
ESCRITA = frozenset({"Write", "Edit", "MultiEdit"})

_SEGREDO = re.compile(
    r"(^|/)(\.env(\..*)?|.*\.pem|.*\.key|id_rsa.*|id_ed25519.*|credentials(\.json)?|"
    r"\.npmrc|\.pypirc|\.netrc|secrets?\.(ya?ml|json))$",
    re.IGNORECASE,
)
_TESTE = re.compile(
    r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]*\.py$|_test\.(py|go)$|\.(test|spec)\.[jt]sx?$"
)
PROTEGIDOS = frozenset({"feature_list.json", "sprint-contract.json", "init.sh"})
ARTEFATOS_APROVADOS = frozenset({"intent.md", "spec.md", "plan.md", "review.md"})


class Etapa(StrEnum):
    EXECUTOR = "executor"
    AVALIADOR = "avaliador"


@dataclass(frozen=True, slots=True)
class Decisao:
    permitido: bool
    motivo: str = ""


PERMITIDO = Decisao(True)


def negado(motivo: str) -> Decisao:
    return Decisao(False, motivo)


@dataclass(frozen=True, slots=True)
class PoliticaDeSessao:
    etapa: Etapa
    intent_id: str
    # Testes que já existiam na base da sessão: editar ou remover é bloqueado.
    testes_existentes: frozenset[str] = frozenset()
    links_simbolicos: frozenset[str] = frozenset()
    refatoracao_de_testes_aprovada: bool = False
    raiz: str = RAIZ_NO_SANDBOX
    executaveis: frozenset[str] = field(default_factory=lambda: EXECUTAVEIS_PADRAO)


EXECUTAVEIS_PADRAO = frozenset(
    {"python", "python3", "pytest", "uv", "pip", "npm", "npx", "node", "go", "make", "cargo",
     "ls", "cat", "head", "tail", "wc", "grep", "diff", "pwd", "true", "sh", "bash"}
)  # fmt: skip
_GIT_E_REDE = frozenset({"git", "curl", "wget", "ssh", "scp", "nc", "rm", "dd", "chmod", "chown"})


def eh_arquivo_de_teste(caminho: str) -> bool:
    return _TESTE.search(caminho) is not None


def _relativo(politica: PoliticaDeSessao, caminho: Any) -> tuple[str | None, Decisao]:
    if not isinstance(caminho, str) or not caminho or "\x00" in caminho:
        return None, negado("caminho ausente ou inválido")
    absoluto = posixpath.normpath(
        caminho if caminho.startswith("/") else posixpath.join(politica.raiz, caminho)
    )
    if absoluto != politica.raiz and not absoluto.startswith(politica.raiz + "/"):
        return None, negado("caminho fora do worktree")
    return absoluto[len(politica.raiz) :].lstrip("/") or ".", PERMITIDO


def _eh_git(relativo: str) -> bool:
    return any(p.lower() == ".git" for p in relativo.split("/"))


def decidir_leitura(politica: PoliticaDeSessao, entrada: Mapping[str, Any]) -> Decisao:
    alvo = entrada.get("file_path") or entrada.get("path") or politica.raiz
    relativo, d = _relativo(politica, alvo)
    if relativo is None:
        return d
    if _eh_git(relativo) or _SEGREDO.search(relativo):
        return negado("leitura de .git ou de arquivo de segredo")
    return PERMITIDO


def decidir_escrita(politica: PoliticaDeSessao, entrada: Mapping[str, Any]) -> Decisao:
    if politica.etapa is not Etapa.EXECUTOR:
        return negado("esta etapa não escreve arquivos")
    relativo, d = _relativo(politica, entrada.get("file_path"))
    if relativo is None:
        return d
    return decidir_caminho_de_escrita(politica, relativo)


def decidir_caminho_de_escrita(politica: PoliticaDeSessao, relativo: str) -> Decisao:
    try:
        caminho_relativo_seguro(relativo)
    except ArtefatoInvalido:
        return negado("caminho de escrita inválido")
    nome = posixpath.basename(relativo)
    if _eh_git(relativo) or _SEGREDO.search(relativo):
        return negado("escrita em .git ou em arquivo de segredo")
    if relativo in politica.links_simbolicos:
        return negado("escrita por link simbólico")
    if nome in PROTEGIDOS:
        return negado(f"{nome} só é alterado pelo harness (grader de código)")
    if relativo.startswith(".forja/"):
        permitido = f".forja/{politica.intent_id}/progress.md"
        if relativo != permitido:
            return negado("em .forja/ só o progress.md da entrega pode ser escrito")
    if relativo in politica.testes_existentes and not politica.refatoracao_de_testes_aprovada:
        return negado("editar teste existente exige issue de refatoração de testes aprovada")
    return PERMITIDO


def decidir_comando(politica: PoliticaDeSessao, argv: object) -> Decisao:
    if not isinstance(argv, list | tuple):
        return negado("comando deve ser uma lista de argumentos")
    itens = cast("Sequence[object]", argv)
    if (
        not itens
        or len(itens) > 30
        or not all(isinstance(a, str) and a and "\x00" not in a for a in itens)
    ):
        return negado("comando deve ser uma lista não vazia de argumentos")
    comando = [str(a) for a in itens]
    exe = posixpath.basename(comando[0])
    if exe in _GIT_E_REDE:
        return negado(f"{exe} não é permitido: o git e a rede são do workflow")
    if exe not in politica.executaveis or exe != comando[0]:
        return negado(f"executável fora da allowlist: {exe[:30]}")
    if exe in ("sh", "bash") and comando[1:] != [f".forja/{politica.intent_id}/init.sh"]:
        return negado("sh/bash só para executar o init.sh da entrega")
    if exe in ("python", "python3") and (
        len(comando) < 2 or comando[1] in ("-c", "-") or comando[1].startswith("-c")
    ):
        return negado("python -c não é permitido")
    if exe in ("python", "python3") and comando[1] == "-m" and comando[2:3] not in (
        ["pytest"], ["unittest"], ["pip"], ["venv"]
    ):  # fmt: skip
        return negado("módulo python fora da allowlist")
    usa_pip = exe == "pip" or comando[:3] == ["python", "-m", "pip"]
    if usa_pip and "install" not in comando and "list" not in comando:
        return negado("pip só para install e list")
    for arg in comando[1:]:
        if arg.startswith("/") and not (
            arg == politica.raiz or arg.startswith(politica.raiz + "/")
        ):
            return negado("argumento aponta para fora do worktree")
        if ".." in arg.split("/"):
            return negado("argumento com `..`")
    return PERMITIDO


def decidir_ferramenta(
    politica: PoliticaDeSessao, ferramenta: str, entrada: Mapping[str, Any]
) -> Decisao:
    """Ponto de entrada único do PreToolUse. Tudo que não é listado aqui é negado."""
    if ferramenta in LEITURA:
        return decidir_leitura(politica, entrada)
    if ferramenta in ESCRITA:
        return decidir_escrita(politica, entrada)
    if ferramenta == FERRAMENTA_EXEC:
        return decidir_comando(politica, entrada.get("argv"))
    if ferramenta.startswith((PREFIXO_MEMORIA, PREFIXO_SKILLS)):
        return PERMITIDO  # a ferramenta de memória valida o próprio caminho e o escopo
    return negado(f"ferramenta não permitida: {ferramenta[:40]}")


# --- auditoria do diff, depois da sessão -----------------------------------------------


@dataclass(frozen=True, slots=True)
class MudancaDeArquivo:
    caminho: str
    status: str  # A, M, D, R, T (como no `git diff --name-status`)
    modo: str = "100644"


def auditar_mudancas(
    politica: PoliticaDeSessao, mudancas: Iterable[MudancaDeArquivo]
) -> tuple[str, ...]:
    """Violações encontradas no diff da sessão. Vazio = limpo. Qualquer uma descarta a sessão."""
    violacoes: list[str] = []
    for m in mudancas:
        if m.modo in ("120000", "160000"):
            violacoes.append(f"{m.caminho}: link simbólico ou gitlink")
            continue
        if m.status == "A":
            d = decidir_caminho_de_escrita(politica, m.caminho)
            if not d.permitido and m.caminho not in politica.testes_existentes:
                violacoes.append(f"{m.caminho}: {d.motivo}")
            continue
        if m.caminho in politica.testes_existentes and not politica.refatoracao_de_testes_aprovada:
            violacoes.append(f"{m.caminho}: teste existente alterado ou removido")
            continue
        d = decidir_caminho_de_escrita(politica, m.caminho)
        if not d.permitido:
            violacoes.append(f"{m.caminho}: {d.motivo}")
    return tuple(violacoes)
