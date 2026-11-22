"""Revisão (seção 5.2, Deploy): achados por revisor, scanner determinístico e review.md.

O revisor de modelo propõe achados; o código valida caminho e linha contra o diff, aplica o
scanner de segredos (que não depende do modelo) e renderiza o review.md.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from forja.domain.artefatos import linha_unica
from forja.domain.politica import Classificacao, Tier

REVISORES = ("seguranca", "testes", "adrs", "desempenho")
_SEGREDO = re.compile(
    r"(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|xox[abp]-[A-Za-z0-9-]{10,})"
)
_ARQUIVO_DE_SEGREDO = re.compile(r"(^|/)(\.env(\..*)?|.*\.pem|id_rsa.*|credentials\.json)$")
_TESTE = re.compile(
    r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]*\.py$|_test\.(py|go)$|\.(test|spec)\.[jt]sx?$"
)


class Severidade(StrEnum):
    BLOQUEANTE = "bloqueante"
    AVISO = "aviso"


@dataclass(frozen=True, slots=True)
class ArquivoDoDiff:
    caminho: str
    status: str
    adicoes: int
    remocoes: int
    patch: str = ""


@dataclass(frozen=True, slots=True)
class DiffDaEntrega:
    arquivos: tuple[ArquivoDoDiff, ...]
    head_sha: str = ""

    @property
    def caminhos(self) -> tuple[str, ...]:
        return tuple(a.caminho for a in self.arquivos)

    @property
    def linhas_alteradas(self) -> int:
        return sum(a.adicoes + a.remocoes for a in self.arquivos)


@dataclass(frozen=True, slots=True)
class Achado:
    revisor: str
    severidade: Severidade
    mensagem: str
    arquivo: str | None = None
    linha: int | None = None
    risco: Tier = Tier.BAIXO

    def __post_init__(self) -> None:
        if self.revisor not in REVISORES:
            raise ValueError(f"revisor desconhecido: {self.revisor[:30]}")


def achado_validado(
    diff: DiffDaEntrega,
    revisor: str,
    severidade: Severidade,
    mensagem: str,
    arquivo: str | None,
    linha: int | None,
    risco: Tier,
) -> Achado:
    """Um achado só aponta para arquivo do diff e linha plausível; o resto é invenção."""
    if arquivo is not None and arquivo not in diff.caminhos:
        raise ValueError(f"achado aponta para arquivo fora do diff: {arquivo[:80]}")
    if linha is not None and (arquivo is None or not 1 <= linha <= 1_000_000):
        raise ValueError("linha inválida")
    return Achado(revisor, severidade, linha_unica(mensagem, 500), arquivo, linha, risco)


def varrer_segredos(diff: DiffDaEntrega) -> tuple[Achado, ...]:
    """Scanner determinístico: o revisor de segurança não é a única barreira contra segredo."""
    achados: list[Achado] = []
    for a in diff.arquivos:
        if a.status != "removed" and _ARQUIVO_DE_SEGREDO.search(a.caminho):
            achados.append(
                Achado(
                    "seguranca",
                    Severidade.BLOQUEANTE,
                    "arquivo de segredo no diff",
                    a.caminho,
                    None,
                    Tier.ALTO,
                )
            )
        for linha in a.patch.splitlines():
            if linha.startswith("+") and _SEGREDO.search(linha):
                achados.append(
                    Achado(
                        "seguranca",
                        Severidade.BLOQUEANTE,
                        "possível segredo em linha adicionada",
                        a.caminho,
                        None,
                        Tier.ALTO,
                    )
                )
                break
    return tuple(achados)


def checar_testes(diff: DiffDaEntrega) -> tuple[Achado, ...]:
    """Grader de código do revisor de testes: código novo sem nenhum teste alterado."""
    codigo = [
        a
        for a in diff.arquivos
        if not _TESTE.search(a.caminho) and a.caminho.endswith((".py", ".go", ".ts", ".js", ".rs"))
    ]
    if codigo and not any(_TESTE.search(a.caminho) for a in diff.arquivos):
        return (
            Achado(
                "testes",
                Severidade.AVISO,
                "mudança de código sem teste alterado ou novo",
                codigo[0].caminho,
                None,
                Tier.MEDIO,
            ),
        )
    return ()


@dataclass(frozen=True, slots=True)
class ResultadoDaRevisao:
    achados: tuple[Achado, ...]
    classificacao: Classificacao

    @property
    def bloqueantes(self) -> tuple[Achado, ...]:
        return tuple(a for a in self.achados if a.severidade is Severidade.BLOQUEANTE)

    @property
    def tier(self) -> Tier:
        return self.classificacao.tier


def tier_com_achados(base: Classificacao, achados: Iterable[Achado]) -> Classificacao:
    """O tier final é o maior entre caminhos, labels e achados dos revisores (seção 9.1)."""
    maior = max([base.tier, *(a.risco for a in achados)])
    motivos = list(base.motivos)
    if maior > base.tier:
        motivos.append("achado de revisor com risco maior")
    return Classificacao(maior, tuple(motivos))


def renderizar_review(resultado: ResultadoDaRevisao, por_revisor: Mapping[str, str]) -> str:
    c = resultado.classificacao
    linhas = ["# review", "", f"## Risco: {c.tier.name.lower()}", ""]
    linhas += [f"- {linha_unica(m, 300)}" for m in c.motivos] or ["- sem motivos de elevação"]
    for nome in REVISORES:
        achados = [a for a in resultado.achados if a.revisor == nome]
        linhas += ["", f"## {nome}", "", linha_unica(por_revisor.get(nome, "sem resumo"), 600), ""]
        for a in achados:
            onde = f" `{a.arquivo}{':' + str(a.linha) if a.linha else ''}`" if a.arquivo else ""
            linhas.append(f"- **{a.severidade.value}**{onde}: {linha_unica(a.mensagem, 500)}")
        if not achados:
            linhas.append("- sem achados")
    return "\n".join(linhas) + "\n"
