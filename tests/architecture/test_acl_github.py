import ast
from pathlib import Path

RAIZ = Path(__file__).parents[2] / "forja"
PROIBIDOS = ("forja.infrastructure", "forja.interfaces", "httpx", "jwt", "fastapi", "redis")
TIPOS_GITHUB = ("IssueCommentEvent", "IssuesEvent", "PullRequestEvent", "X-Hub-Signature", "X-GitHub")


def _arquivos(camada: str) -> list[Path]:
    return sorted((RAIZ / camada).rglob("*.py"))


def _importados(arquivo: Path) -> list[str]:
    nomes: list[str] = []
    for no in ast.walk(ast.parse(arquivo.read_text())):
        if isinstance(no, ast.Import):
            nomes += [a.name for a in no.names]
        elif isinstance(no, ast.ImportFrom) and no.module:
            nomes.append(no.module)
    return nomes


def test_dominio_e_aplicacao_nao_importam_infraestrutura_nem_clientes() -> None:
    for camada in ("domain", "application"):
        for arquivo in _arquivos(camada):
            for nome in _importados(arquivo):
                assert not nome.startswith(PROIBIDOS), f"{arquivo} importa {nome}"


def test_nenhum_tipo_do_github_fora_de_infrastructure_github() -> None:
    for camada in ("domain", "application"):
        for arquivo in _arquivos(camada):
            texto = arquivo.read_text()
            for tipo in TIPOS_GITHUB:
                assert tipo not in texto, f"{arquivo} menciona {tipo}"
