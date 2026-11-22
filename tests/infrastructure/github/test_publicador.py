# pyright: basic
import fakeredis
import pytest

from forja.application.portas.publicador import PublicacaoEmAndamento
from forja.infrastructure.github.publicador import PublicadorGitHub
from forja.infrastructure.persistencia.idempotencia_redis import IdempotenciaRedis


class GitHubGravador:
    def __init__(self) -> None:
        self.comentarios: list[str] = []
        self.falhar = False

    async def comentar_issue(self, repositorio: str, numero: int, corpo: str) -> None:
        if self.falhar:
            raise RuntimeError("github fora")
        self.comentarios.append(corpo)

    async def criar_branch(self, repositorio: str, intent_id: str, slug: str) -> str:
        raise AssertionError


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
