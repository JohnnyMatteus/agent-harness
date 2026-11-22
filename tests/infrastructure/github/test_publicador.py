# pyright: basic
import fakeredis
import pytest

from forja.application.portas.publicador import PublicacaoEmAndamento
from forja.domain.artefatos import ArtefatoInvalido
from forja.infrastructure.github.publicador import PublicadorGitHub
from forja.infrastructure.persistencia.idempotencia_redis import IdempotenciaRedis


class GitHubGravador:
    def __init__(self) -> None:
        self.comentarios: list[str] = []
        self.falhar = False
        self.branches: list[str] = []
        self.arquivos: dict[tuple[str, str], str] = {}
        self.prs: list[tuple[str, str, bool]] = []

    async def comentar_issue(self, repositorio: str, numero: int, corpo: str) -> None:
        if self.falhar:
            raise RuntimeError("github fora")
        self.comentarios.append(corpo)

    async def criar_branch(self, repositorio: str, intent_id: str, slug: str) -> str:
        self.branches.append(f"{intent_id}-{slug}")
        return f"forja/{intent_id}-{slug}"

    async def commitar_arquivo(
        self, repositorio: str, branch: str, caminho: str, conteudo: str, mensagem: str
    ) -> bool:
        if self.falhar:
            raise RuntimeError("github fora")
        self.arquivos[(branch, caminho)] = conteudo
        return True

    async def ler_arquivo(self, repositorio: str, branch: str, caminho: str) -> str | None:
        return self.arquivos.get((branch, caminho))

    async def abrir_pr(
        self, repositorio: str, branch: str, titulo: str, corpo: str, rascunho: bool
    ) -> str:
        self.prs.append((titulo, corpo, rascunho))
        return "https://github.test/pr/1"


def montar(dry_run: bool = False):
    gh = GitHubGravador()
    redis = fakeredis.FakeAsyncRedis()
    return (
        gh,
        IdempotenciaRedis(redis),
        PublicadorGitHub(gh, IdempotenciaRedis(redis), dry_run=dry_run),
    )


async def test_dry_run_e_o_padrao_e_nao_escreve() -> None:
    gh = GitHubGravador()
    pub = PublicadorGitHub(gh, IdempotenciaRedis(fakeredis.FakeAsyncRedis()))
    assert await pub.comentar("a/b", 1, "oi", "k") == "dry_run"
    assert gh.comentarios == []


async def test_idempotente_por_chave_inclusive_em_concorrencia() -> None:
    import asyncio

    gh, _, pub = montar()
    resultados = await asyncio.gather(
        *(pub.comentar("a/b", 1, "oi", "k") for _ in range(5)), return_exceptions=True
    )
    assert gh.comentarios == ["oi"]
    assert resultados.count("publicado") == 1
    assert await pub.comentar("a/b", 1, "oi", "k") == "ja_publicado"
    assert all(
        r in ("publicado", "ja_publicado") or isinstance(r, PublicacaoEmAndamento)
        for r in resultados
    )


async def test_falha_libera_a_chave_para_a_retentativa() -> None:
    gh, _, pub = montar()
    gh.falhar = True
    with pytest.raises(RuntimeError):
        await pub.comentar("a/b", 1, "oi", "k")
    gh.falhar = False
    assert await pub.comentar("a/b", 1, "oi", "k") == "publicado"


async def test_corpo_e_neutralizado_na_saida_e_destino_e_validado() -> None:
    gh, _, pub = montar()
    await pub.comentar("a/b", 1, "chamando @alguem <!-- x -->", "k")
    assert "@alguem" not in gh.comentarios[0] and "<!--" not in gh.comentarios[0]
    with pytest.raises(ValueError, match="inválido"):
        await pub.comentar("../x", 1, "oi", "k2")
    with pytest.raises(ValueError, match="inválido"):
        await pub.comentar("a/b", 0, "oi", "k3")


ID = "0123456789abcdef"


def destino():
    from forja.application.portas.publicador import DestinoDaEntrega

    return DestinoDaEntrega("a/b", ID, "corrige-login")


async def test_artefato_vai_para_o_caminho_fixo_e_e_idempotente() -> None:
    gh, _, pub = montar()
    assert await pub.commitar_artefato(destino(), "spec.md", "# spec", "msg") == "publicado"
    assert await pub.commitar_artefato(destino(), "spec.md", "# spec", "msg") == "ja_publicado"
    assert gh.arquivos == {(f"forja/{ID}-corrige-login", f".forja/{ID}/spec.md"): "# spec"}
    assert await pub.ler_artefato(destino(), "spec.md") == "# spec"
    for ruim in ("../x", "spec.md/../../y", "outro.txt"):
        with pytest.raises(ArtefatoInvalido):
            await pub.commitar_artefato(destino(), ruim, "x", "m")


async def test_artefato_e_pr_em_dry_run_nao_escrevem() -> None:
    gh = GitHubGravador()
    pub = PublicadorGitHub(gh, IdempotenciaRedis(fakeredis.FakeAsyncRedis()))
    assert await pub.commitar_artefato(destino(), "plan.md", "x", "m") == "dry_run"
    assert await pub.abrir_pr(destino(), "t", "c") == "dry-run"
    assert await pub.ler_artefato(destino(), "plan.md") is None
    assert gh.arquivos == {} and gh.prs == [] and gh.branches == []


async def test_pr_e_rascunho_e_corpo_neutralizado() -> None:
    gh, _, pub = montar()
    await pub.abrir_pr(destino(), "título @x", "![](https://evil/?d=1) @dono")
    titulo, corpo, rascunho = gh.prs[0]
    assert rascunho and "://" not in corpo and "@dono" not in corpo and "@x" not in titulo


async def test_destino_invalido_e_recusado() -> None:
    from forja.application.portas.publicador import DestinoDaEntrega

    _, _, pub = montar()
    with pytest.raises(ValueError, match="inválido"):
        await pub.abrir_pr(DestinoDaEntrega("../x", ID, "s"), "t", "c")
    with pytest.raises(ValueError, match="inválido"):
        await pub.abrir_pr(DestinoDaEntrega("a/b", "../../x", "s"), "t", "c")
