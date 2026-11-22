# pyright: basic
import importlib.util
from pathlib import Path

import pytest

CAMINHO = Path(__file__).parents[2] / "infra" / "ci" / "verificar_evals.py"
spec = importlib.util.spec_from_file_location("verificar_evals", CAMINHO)
assert spec is not None and spec.loader is not None
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def xml(tests=5, failures=0, errors=0, skipped=0) -> str:
    return (
        f'<testsuites><testsuite name="pytest" tests="{tests}" failures="{failures}" '
        f'errors="{errors}" skipped="{skipped}"></testsuite></testsuites>'
    )


def test_tudo_rodou_e_passou() -> None:
    assert gate.problemas(xml()) == []


@pytest.mark.parametrize(
    ("conteudo", "trecho"),
    [
        (xml(tests=0), "zero tarefas"),
        (xml(failures=1), "failure"),
        (xml(errors=1), "error"),
        (xml(skipped=1), "skipped"),  # pulou: nunca é verde
        ("<nao-xml", "ilegível"),
        ('<testsuites><testsuite name="p"></testsuite></testsuites>', "zero tarefas"),
    ],
)
def test_zero_tarefas_falha_ou_skip_e_erro_sao_falha(conteudo: str, trecho: str) -> None:
    assert any(trecho in p for p in gate.problemas(conteudo))


def test_minimo_de_testes_e_exigido() -> None:
    assert gate.problemas(xml(tests=3), minimo=10)
    assert gate.problemas(xml(tests=10), minimo=10) == []


def test_main_devolve_codigo_de_saida(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ok = tmp_path / "ok.xml"
    ok.write_text(xml(), encoding="utf-8")
    ruim = tmp_path / "ruim.xml"
    ruim.write_text(xml(skipped=2), encoding="utf-8")
    assert gate.main([str(ok)]) == 0
    assert gate.main([str(ruim)]) == 1 and "skipped" in capsys.readouterr().out
    assert gate.main([str(tmp_path / "nao-existe.xml")]) == 1  # sem arquivo, falha
    assert gate.main([]) == 2
