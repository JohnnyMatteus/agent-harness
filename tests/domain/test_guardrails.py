import pytest

from forja.domain.guardrails import (
    FERRAMENTA_EXEC,
    Etapa,
    MudancaDeArquivo,
    PoliticaDeSessao,
    auditar_mudancas,
    decidir_ferramenta,
    eh_arquivo_de_teste,
)

ID = "0123456789abcdef"
EX = PoliticaDeSessao(
    Etapa.EXECUTOR,
    ID,
    testes_existentes=frozenset({"tests/test_a.py"}),
    links_simbolicos=frozenset({"atalho.py"}),
)
AV = PoliticaDeSessao(Etapa.AVALIADOR, ID)


def pode(politica: PoliticaDeSessao, ferramenta: str, **entrada: object) -> bool:
    return decidir_ferramenta(politica, ferramenta, entrada).permitido


@pytest.mark.parametrize(
    ("ferramenta", "entrada", "esperado"),
    [
        ("Write", {"file_path": "/workspace/src/a.py"}, True),
        ("Edit", {"file_path": "src/a.py"}, True),
        ("Write", {"file_path": "/workspace/tests/test_novo.py"}, True),
        ("Write", {"file_path": "/etc/passwd"}, False),
        ("Write", {"file_path": "/workspace/../etc/passwd"}, False),
        ("Write", {"file_path": "../x"}, False),
        ("Write", {"file_path": "/workspacex/a"}, False),
        ("Write", {"file_path": "/workspace/.git/hooks/pre-commit"}, False),
        ("Write", {"file_path": "/workspace/.env"}, False),
        ("Write", {"file_path": "/workspace/config/server.pem"}, False),
        ("Write", {"file_path": "/workspace/feature_list.json"}, False),
        ("Edit", {"file_path": "/workspace/.forja/" + ID + "/feature_list.json"}, False),
        ("Write", {"file_path": "/workspace/.forja/" + ID + "/spec.md"}, False),
        ("Write", {"file_path": "/workspace/.forja/" + ID + "/progress.md"}, True),
        ("Write", {"file_path": "/workspace/.forja/outro/progress.md"}, False),
        ("Write", {"file_path": "/workspace/init.sh"}, False),
        ("Edit", {"file_path": "/workspace/tests/test_a.py"}, False),
        ("Write", {"file_path": "/workspace/atalho.py"}, False),
        ("Write", {}, False),
        ("Write", {"file_path": 3}, False),
        ("Read", {"file_path": "/workspace/src/a.py"}, True),
        ("Read", {"file_path": "/proc/self/environ"}, False),
        ("Read", {"file_path": "/workspace/.git/config"}, False),
        ("Grep", {"path": "/workspace/.env.local"}, False),
        ("Glob", {"path": "/"}, False),
        ("Bash", {"command": "ls"}, False),
        ("WebFetch", {"url": "https://x"}, False),
        ("mcp__outro__tool", {}, False),
        ("mcp__memoria__view", {"path": "/memories"}, True),
    ],
)
def test_executor_pre_tool_use(ferramenta: str, entrada: dict[str, object], esperado: bool) -> None:
    assert pode(EX, ferramenta, **entrada) is esperado


def test_edicao_de_teste_existente_so_com_refatoracao_aprovada() -> None:
    aprovada = PoliticaDeSessao(
        Etapa.EXECUTOR, ID, frozenset({"tests/test_a.py"}), refatoracao_de_testes_aprovada=True
    )
    assert pode(aprovada, "Edit", file_path="/workspace/tests/test_a.py")


def test_avaliador_nunca_escreve_mas_le() -> None:
    assert not pode(AV, "Write", file_path="/workspace/src/a.py")
    assert pode(AV, "Read", file_path="/workspace/src/a.py")


@pytest.mark.parametrize(
    ("argv", "esperado"),
    [
        (["pytest", "-q"], True),
        (["python", "-m", "pytest", "tests"], True),
        (["uv", "run", "pytest"], True),
        (["npm", "test"], True),
        (["bash", f".forja/{ID}/init.sh"], True),
        (["bash", "init.sh"], False),
        (["pip", "install", "requests"], True),
        (["ls", "src"], True),
        (["git", "push"], False),
        (["git", "commit", "-m", "x"], False),
        (["curl", "https://evil.test"], False),
        (["rm", "-rf", "/"], False),
        (["/bin/rm", "x"], False),
        (["python", "-c", "open('x','w')"], False),
        (["python", "-m", "http.server"], False),
        (["python"], False),
        (["bash", "-c", "x"], False),
        (["sh", "evil.sh"], False),
        (["cat", "/etc/passwd"], False),
        (["cat", "../../etc/passwd"], False),
        (["cat", "/workspace/README.md"], True),
        (["pip", "uninstall", "x"], False),
        ([], False),
        ("pytest", False),
        (["pytest", ""], False),
        (["pytest"] * 40, False),
    ],
)
def test_comando_no_sandbox(argv: object, esperado: bool) -> None:
    assert pode(EX, FERRAMENTA_EXEC, argv=argv) is esperado


def test_auditoria_pega_o_que_o_hook_nao_ve() -> None:
    def m(c: str, s: str = "M", modo: str = "100644") -> MudancaDeArquivo:
        return MudancaDeArquivo(c, s, modo)

    limpo = [m("src/a.py"), m("tests/test_novo.py", "A"), m(f".forja/{ID}/progress.md")]
    assert auditar_mudancas(EX, limpo) == ()
    ruins = [
        m("tests/test_a.py"),
        m("tests/test_a.py", "D"),
        m("feature_list.json"),
        m(f".forja/{ID}/spec.md"),
        m("link", "A", "120000"),
        m(".env", "A"),
        m("init.sh", "D"),
    ]
    assert len(auditar_mudancas(EX, ruins)) == len(ruins)


@pytest.mark.parametrize(
    "caminho",
    [
        "tests/a.py",
        "src/tests/x.py",
        "test_x.py",
        "pkg/test_x.py",
        "a_test.go",
        "a.test.ts",
        "web/a.spec.js",
    ],
)
def test_reconhece_arquivo_de_teste(caminho: str) -> None:
    assert eh_arquivo_de_teste(caminho)
    assert not eh_arquivo_de_teste("src/contest.py")
