"""Regra de dependência: domain não conhece nada; application só conhece domain."""

import ast
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2] / "forja"
STDLIB = sys.stdlib_module_names

PERMITIDO = {
    "domain": {"forja.domain"},
    "application": {"forja.domain", "forja.application"},
}


def importacoes(arquivo: Path) -> list[str]:
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
    nomes: list[str] = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            nomes += [a.name for a in no.names]
        elif isinstance(no, ast.ImportFrom) and no.module and no.level == 0:
            nomes.append(no.module)
    return nomes


def permitido(nome: str, camada: str) -> bool:
    raiz = nome.split(".")[0]
    if raiz in STDLIB:
        return True
    return any(nome == p or nome.startswith(p + ".") for p in PERMITIDO[camada])


@pytest.mark.parametrize("camada", sorted(PERMITIDO))
def test_camada_so_importa_o_permitido(camada: str) -> None:
    violacoes = [
        f"{arquivo.relative_to(RAIZ.parent)} importa {nome}"
        for arquivo in (RAIZ / camada).rglob("*.py")
        for nome in importacoes(arquivo)
        if not permitido(nome, camada)
    ]
    assert violacoes == []


def test_detector_pega_violacao(tmp_path: Path) -> None:
    ruim = tmp_path / "ruim.py"
    ruim.write_text("import fastapi\nfrom forja.infrastructure.github import x\n")
    assert [n for n in importacoes(ruim) if not permitido(n, "domain")] == [
        "fastapi",
        "forja.infrastructure.github",
    ]
