"""Chunking por estrutura: tree-sitter para código, cabeçalhos para Markdown, janelas no resto."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from forja.application.portas.knowledge import Particao
from forja.domain.knowledge import TipoDeTrecho, TrechoBruto

LINGUAGENS_DE_CODIGO = {".py": "python", ".ts": "typescript"}
LINGUAGENS_DE_TEXTO = {
    ".md": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".json": "json",
    ".sql": "sql",
    ".sh": "shell",
    ".txt": "texto",
}
EXTENSOES_SUPORTADAS = frozenset(LINGUAGENS_DE_CODIGO) | frozenset(LINGUAGENS_DE_TEXTO)

_CABECALHO = re.compile(r"^(#{1,6})\s+(\S.*?)\s*#*\s*$")
_CERCA = re.compile(r"^\s*(```|~~~)")


@dataclass(frozen=True, slots=True)
class _Gramatica:
    linguagem: Language
    definicoes: frozenset[str]
    classes: frozenset[str]
    metodos: frozenset[str]
    corpo_da_classe: str


def _gramatica_python() -> _Gramatica:
    return _Gramatica(
        Language(tree_sitter_python.language()),
        frozenset({"function_definition", "class_definition", "decorated_definition"}),
        frozenset({"class_definition"}),
        frozenset({"function_definition", "decorated_definition"}),
        "body",
    )


def _gramatica_typescript() -> _Gramatica:
    return _Gramatica(
        Language(tree_sitter_typescript.language_typescript()),
        frozenset(
            {
                "function_declaration",
                "class_declaration",
                "interface_declaration",
                "type_alias_declaration",
                "enum_declaration",
                "lexical_declaration",
                "export_statement",
            }
        ),
        frozenset({"class_declaration"}),
        frozenset({"method_definition"}),
        "body",
    )


def _nome(no: Node) -> str | None:
    if no.type in {"decorated_definition", "export_statement"}:
        interno = no.child_by_field_name("definition") or no.child_by_field_name("declaration")
        return _nome(interno) if interno else None
    if no.type == "lexical_declaration":
        for filho in no.named_children:
            if filho.type == "variable_declarator":
                return _nome(filho)
        return None
    campo = no.child_by_field_name("name")
    return campo.text.decode("utf-8", "replace") if campo and campo.text else None


def _desembrulhar(no: Node) -> Node:
    while no.type in {"decorated_definition", "export_statement"}:
        interno = no.child_by_field_name("definition") or no.child_by_field_name("declaration")
        if interno is None:
            break
        no = interno
    return no


class ChunkerEstrutural:
    """Divide um arquivo em trechos com símbolo, linhas e conteúdo.

    Trechos acima de `max_chars` são partidos em janelas de linhas com pequena sobreposição.
    """

    versao = "chunker-1"

    def __init__(self, max_chars: int = 2400, sobreposicao_linhas: int = 3) -> None:
        self._max = max_chars
        self._sobreposicao = sobreposicao_linhas
        self._parsers: dict[str, tuple[Parser, _Gramatica]] = {}

    def dividir(self, caminho: str, texto: str) -> Particao:
        extensao = PurePosixPath(caminho).suffix.lower()
        linhas = texto.splitlines()
        if extensao in LINGUAGENS_DE_CODIGO:
            linguagem = LINGUAGENS_DE_CODIGO[extensao]
            brutos = self._codigo(linguagem, texto, linhas)
            tipo = TipoDeTrecho.CODIGO
        elif extensao == ".md":
            linguagem = "markdown"
            brutos = self._markdown(linhas)
            partes = PurePosixPath(caminho).parts
            tipo = TipoDeTrecho.ADR if "adr" in partes else TipoDeTrecho.DOC
        else:
            linguagem = LINGUAGENS_DE_TEXTO.get(extensao, "texto")
            brutos = []
            tipo = TipoDeTrecho.CODIGO
        if not brutos and linhas:
            brutos = [TrechoBruto(None, 1, len(linhas), "\n".join(linhas))]
        limitados = [parte for bruto in brutos for parte in self._limitar(bruto)]
        return Particao(linguagem, tipo, tuple(t for t in limitados if t.conteudo.strip()))

    def _parser(self, linguagem: str) -> tuple[Parser, _Gramatica]:
        if linguagem not in self._parsers:
            fabrica: Callable[[], _Gramatica] = (
                _gramatica_python if linguagem == "python" else _gramatica_typescript
            )
            gramatica = fabrica()
            self._parsers[linguagem] = (Parser(gramatica.linguagem), gramatica)
        return self._parsers[linguagem]

    def _codigo(self, linguagem: str, texto: str, linhas: list[str]) -> list[TrechoBruto]:
        parser, gramatica = self._parser(linguagem)
        raiz = parser.parse(texto.encode("utf-8")).root_node
        brutos: list[TrechoBruto] = []
        resto: list[tuple[int, int]] = []

        def fechar_resto() -> None:
            if resto:
                brutos.append(self._faixa(linhas, resto[0][0], resto[-1][1], "<modulo>"))
                resto.clear()

        for filho in raiz.children:
            inicio, fim = filho.start_point.row, filho.end_point.row
            if filho.type in gramatica.definicoes and (nome := _nome(filho)):
                fechar_resto()
                brutos += self._definicao(gramatica, filho, nome, linhas)
            elif filho.is_named:
                resto.append((inicio, fim))
        fechar_resto()
        return brutos

    def _definicao(
        self, gramatica: _Gramatica, no: Node, nome: str, linhas: list[str]
    ) -> list[TrechoBruto]:
        inicio, fim = no.start_point.row, no.end_point.row
        interno = _desembrulhar(no)
        inteiro = self._faixa(linhas, inicio, fim, nome)
        if interno.type not in gramatica.classes or len(inteiro.conteudo) <= self._max:
            return [inteiro]
        corpo = interno.child_by_field_name(gramatica.corpo_da_classe)
        metodos = [m for m in corpo.named_children if m.type in gramatica.metodos] if corpo else []
        if not metodos:
            return [inteiro]
        # Fronteiras contíguas: nenhum texto da classe se perde entre os métodos.
        inicios = [m.start_point.row for m in metodos]
        brutos = [self._faixa(linhas, inicio, inicios[0] - 1, nome)]
        for i, metodo in enumerate(metodos):
            limite = inicios[i + 1] - 1 if i + 1 < len(metodos) else fim
            brutos.append(self._faixa(linhas, inicios[i], limite, f"{nome}.{_nome(metodo) or '?'}"))
        return [b for b in brutos if b.conteudo.strip()]

    @staticmethod
    def _faixa(linhas: list[str], inicio: int, fim: int, simbolo: str | None) -> TrechoBruto:
        fim = max(fim, inicio)
        return TrechoBruto(simbolo, inicio + 1, fim + 1, "\n".join(linhas[inicio : fim + 1]))

    def _markdown(self, linhas: list[str]) -> list[TrechoBruto]:
        secoes: list[tuple[int, str | None]] = [(0, None)]
        pilha: list[tuple[int, str]] = []
        em_cerca = False
        for i, linha in enumerate(linhas):
            if _CERCA.match(linha):
                em_cerca = not em_cerca
            elif not em_cerca and (m := _CABECALHO.match(linha)):
                nivel = len(m.group(1))
                while pilha and pilha[-1][0] >= nivel:
                    pilha.pop()
                pilha.append((nivel, m.group(2)))
                secoes.append((i, " > ".join(t for _, t in pilha)))
        brutos: list[TrechoBruto] = []
        for n, (inicio, simbolo) in enumerate(secoes):
            fim = (secoes[n + 1][0] if n + 1 < len(secoes) else len(linhas)) - 1
            if fim >= inicio:
                brutos.append(self._faixa(linhas, inicio, fim, simbolo))
        return brutos

    def _limitar(self, bruto: TrechoBruto) -> list[TrechoBruto]:
        if len(bruto.conteudo) <= self._max:
            return [bruto]
        linhas = bruto.conteudo.splitlines()
        partes: list[TrechoBruto] = []
        inicio = 0
        while inicio < len(linhas):
            tamanho = fim = inicio
            while fim < len(linhas) and (
                tamanho + len(linhas[fim]) + 1 <= self._max or fim == inicio
            ):
                tamanho += len(linhas[fim]) + 1
                fim += 1
            partes.append(
                TrechoBruto(
                    bruto.simbolo,
                    bruto.linha_inicio + inicio,
                    bruto.linha_inicio + fim - 1,
                    "\n".join(linhas[inicio:fim]),
                )
            )
            if fim >= len(linhas):
                break
            inicio = max(fim - self._sobreposicao, inicio + 1)
        return partes
