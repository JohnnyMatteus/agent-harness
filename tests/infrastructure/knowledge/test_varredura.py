import os
from pathlib import Path

import pytest

from forja.infrastructure.knowledge.chunker import ChunkerEstrutural
from forja.infrastructure.knowledge.varredura import VarreduraDeDiretorio, contem_segredo

# Montados em tempo de execução para não deixar nada parecido com segredo no repositório.
CHAVE_AWS = "AKIA" + "B" * 16
CHAVE_PRIVADA = "-----BEGIN " + "RSA PRIVATE KEY-----\nabc\n"


def varrer(
    raiz: Path, max_bytes_por_arquivo: int = 4096, max_arquivos: int = 100
) -> tuple[dict[str, str], dict[str, int]]:
    v = VarreduraDeDiretorio(
        raiz, "c0ffee", max_bytes_por_arquivo=max_bytes_por_arquivo, max_arquivos=max_arquivos
    ).varrer()
    return {a.caminho: a.conteudo for a in v.arquivos}, v.recusados


def test_aceita_texto_suportado_com_caminho_relativo_posix(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("def f():\n    return 1\n")
    (tmp_path / "foto.png").write_bytes(b"\x89PNG")
    arquivos, recusados = varrer(tmp_path)
    assert list(arquivos) == ["pkg/a.py"]
    assert recusados == {"extensao": 1}


def test_nao_segue_symlink_de_arquivo_nem_de_diretorio(tmp_path: Path) -> None:
    fora = tmp_path / "fora"
    fora.mkdir()
    (fora / "alvo.py").write_text("x = 1\n")
    raiz = tmp_path / "repo"
    raiz.mkdir()
    (raiz / "ok.py").write_text("y = 2\n")
    os.symlink(fora / "alvo.py", raiz / "link.py")
    os.symlink(fora, raiz / "dir")
    arquivos, recusados = varrer(raiz)
    assert list(arquivos) == ["ok.py"]
    assert recusados == {"symlink": 1}


@pytest.mark.parametrize(
    ("nome", "conteudo"),
    [
        (".env", "A=1\n"),
        ("deploy.pem", "x"),
        ("id_rsa", "x"),
        ("chaves.py", f'K = "{CHAVE_AWS}"\n'),
        ("tls.txt", CHAVE_PRIVADA),
        ("cfg.yaml", 'password: "umasenhalonga123"\n'),
    ],
)
def test_recusa_segredo_por_nome_ou_conteudo(tmp_path: Path, nome: str, conteudo: str) -> None:
    (tmp_path / nome).write_text(conteudo)
    arquivos, recusados = varrer(tmp_path)
    assert arquivos == {}
    assert recusados == {"segredo": 1}


def test_recusa_binario_grande_e_nao_utf8(tmp_path: Path) -> None:
    (tmp_path / "bin.txt").write_bytes(b"ab\x00cd")
    (tmp_path / "grande.txt").write_text("a" * 200)
    (tmp_path / "latin.txt").write_bytes("açaí".encode("latin-1"))
    arquivos, recusados = varrer(tmp_path, max_bytes_por_arquivo=100)
    assert arquivos == {}
    assert recusados == {"binario": 1, "grande": 1, "nao_utf8": 1}


def test_limita_quantidade_de_arquivos(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"f{i}.txt").write_text("x")
    arquivos, recusados = varrer(tmp_path, max_arquivos=2)
    assert len(arquivos) == 2
    assert recusados == {"limite_total": 3}


def test_ignora_diretorios_de_dependencia(tmp_path: Path) -> None:
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.ts").write_text("export const a = 1;")
    assert varrer(tmp_path)[0] == {}


def test_texto_comum_nao_e_segredo() -> None:
    assert not contem_segredo("token = obter_token()\npassword = None\n")


@pytest.mark.timeout(10)
def test_fifo_nao_trava_a_varredura(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "pipe.md")
    (tmp_path / "ok.md").write_text("# x\n")
    arquivos, recusados = varrer(tmp_path)
    assert list(arquivos) == ["ok.md"]
    assert recusados == {"nao_regular": 1}


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignora permissões")
def test_diretorio_ilegivel_fica_em_nao_lidos(tmp_path: Path) -> None:
    (tmp_path / "bloqueado").mkdir()
    (tmp_path / "bloqueado" / "a.py").write_text("x = 1\n")
    (tmp_path / "ok.py").write_text("y = 1\n")
    (tmp_path / "bloqueado").chmod(0)
    try:
        v = VarreduraDeDiretorio(tmp_path, "c").varrer()
    finally:
        (tmp_path / "bloqueado").chmod(0o700)
    assert [a.caminho for a in v.arquivos] == ["ok.py"]
    assert v.nao_lidos == ("bloqueado",)


@pytest.mark.timeout(10)
@pytest.mark.parametrize(
    "linha",
    [
        "# a" + " " * 200_000 + "b",
        "#" * 200_000,
        "# " + "a #" * 70_000,
        "password" + " " * 200_000,
        "password=" + '"' + "a" * 200_000,
        "ghp_" + "a" * 200_000,
    ],
)
def test_linha_hostil_enorme_nao_trava(tmp_path: Path, linha: str) -> None:
    (tmp_path / "a.md").write_text(linha)
    VarreduraDeDiretorio(tmp_path, "c").varrer()
    ChunkerEstrutural().dividir("a.md", linha)
