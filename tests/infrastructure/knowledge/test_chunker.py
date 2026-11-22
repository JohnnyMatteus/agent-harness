from forja.domain.knowledge import TipoDeTrecho
from forja.infrastructure.knowledge.chunker import ChunkerEstrutural

PY = '''import os

LIMITE = 3


def validar(x):
    """Valida x."""
    return x > LIMITE


@decorador
class Servico:
    """Faz coisas."""

    def um(self):
        return 1

    def dois(self):
        return 2
'''


def simbolos(caminho: str, texto: str, **kw: int) -> dict[str | None, str]:
    p = ChunkerEstrutural(**kw).dividir(caminho, texto)
    return {t.simbolo: t.conteudo for t in p.trechos}


def test_python_divide_por_funcao_classe_e_resto_do_modulo() -> None:
    particao = ChunkerEstrutural().dividir("src/a.py", PY)
    assert [t.simbolo for t in particao.trechos] == ["<modulo>", "validar", "Servico"]
    assert particao.linguagem == "python"
    assert particao.tipo is TipoDeTrecho.CODIGO
    validar = particao.trechos[1]
    assert (validar.linha_inicio, validar.linha_fim) == (6, 8)
    assert '"""Valida x."""' in validar.conteudo
    assert particao.trechos[2].conteudo.startswith("@decorador")


def test_classe_grande_vira_um_trecho_por_metodo_sem_perder_texto() -> None:
    s = simbolos("a.py", PY, max_chars=120)
    assert {"Servico", "Servico.um", "Servico.dois"} <= set(s)
    assert "return 2" in s["Servico.dois"]
    assert '"""Faz coisas."""' in s["Servico"]


def test_typescript_funcao_classe_e_const() -> None:
    ts = (
        "export function soma(a: number, b: number) {\n  return a + b;\n}\n"
        "export const dobro = (n: number) => n * 2;\n"
        "interface Opcoes { a: string }\n"
        "class Caixa {\n  abrir() {}\n}\n"
    )
    assert [t for t in simbolos("a.ts", ts) if t != "<modulo>"] == [
        "soma",
        "dobro",
        "Opcoes",
        "Caixa",
    ]


def test_markdown_por_cabecalho_ignora_cerca_de_codigo() -> None:
    md = (
        "# Título\nintro\n## Decisão\ntexto\n```\n# comentário, não é cabeçalho\n```\n## Outra\nx\n"
    )
    particao = ChunkerEstrutural().dividir("docs/adr/0001-x.md", md)
    assert [t.simbolo for t in particao.trechos] == ["Título", "Título > Decisão", "Título > Outra"]
    assert particao.tipo is TipoDeTrecho.ADR
    assert "comentário" in particao.trechos[1].conteudo
    assert ChunkerEstrutural().dividir("README.md", md).tipo is TipoDeTrecho.DOC


def test_trecho_grande_e_partido_com_sobreposicao_e_limite() -> None:
    linhas = [f"linha numero {i:03d} " + "x" * 30 for i in range(60)]
    particao = ChunkerEstrutural(max_chars=400, sobreposicao_linhas=2).dividir(
        "a.txt", "\n".join(linhas)
    )
    assert len(particao.trechos) > 3
    assert all(len(t.conteudo) <= 400 for t in particao.trechos)
    a, b = particao.trechos[0], particao.trechos[1]
    assert b.linha_inicio <= a.linha_fim  # sobreposição
    assert particao.trechos[-1].linha_fim == 60


def test_codigo_sem_definicao_cai_para_o_arquivo_inteiro_e_vazio_nao_gera_trecho() -> None:
    assert simbolos("a.py", "x = 1\n") == {"<modulo>": "x = 1"}
    assert ChunkerEstrutural().dividir("a.py", "").trechos == ()
