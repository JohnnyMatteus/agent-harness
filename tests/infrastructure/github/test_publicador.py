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


async def test_commit_leva_trailers_em_linhas_proprias() -> None:
    capturadas: list[str] = []

    class Gravador(GitHubGravador):
        async def commitar_arquivo(self, repositorio, branch, caminho, conteudo, mensagem):
            capturadas.append(mensagem)
            return True

    pub = PublicadorGitHub(Gravador(), IdempotenciaRedis(fakeredis.FakeAsyncRedis()), dry_run=False)
    await pub.commitar_artefato(
        destino(), "intent.md", "x", f"forja(plan): intent.md\n\nIntent-Id: {ID}\nRun-Id: r"
    )
    assert capturadas == [f"forja(plan): intent.md\n\nIntent-Id: {ID}\nRun-Id: r"]


async def test_erro_ao_ler_artefato_sobe_em_vez_de_virar_ausencia() -> None:
    class Quebrado(GitHubGravador):
        async def ler_arquivo(self, repositorio, branch, caminho):
            raise RuntimeError("github 500")

    pub = PublicadorGitHub(Quebrado(), IdempotenciaRedis(fakeredis.FakeAsyncRedis()), dry_run=False)
    with pytest.raises(RuntimeError, match="500"):
        await pub.ler_artefato(destino(), "spec.md")
    assert await montar()[2].ler_artefato(destino(), "spec.md") is None  # ausente é None


class ClienteDeRevisaoGravador:
    def __init__(self) -> None:
        self.checks, self.prontos, self.merges = [], [], []

    async def criar_check_run(
        self, repositorio, head_sha, nome, conclusao, titulo, resumo, anotacoes
    ):
        self.checks.append((nome, conclusao, anotacoes))

    async def marcar_pr_pronto(self, repositorio, numero):
        self.prontos.append(numero)

    async def mesclar_pr(self, repositorio, numero, sha):
        self.merges.append((numero, sha))

    async def criar_issue(self, repositorio, titulo, corpo, rotulos):
        self.issues = getattr(self, "issues", [])
        self.issues.append((titulo, corpo, rotulos))
        return "https://github.test/issues/1"


def _publicador_de_revisao(dry_run=False):
    cliente = ClienteDeRevisaoGravador()
    pub = PublicadorGitHub(
        GitHubGravador(),
        IdempotenciaRedis(fakeredis.FakeAsyncRedis()),
        dry_run=dry_run,
        revisao=cliente,
    )
    return pub, cliente


SHA = "a" * 40


async def test_check_run_leva_anotacoes_neutralizadas_conclusao_e_e_idempotente() -> None:
    from forja.domain.politica import Tier
    from forja.domain.revisao import Achado, Severidade

    pub, cliente = _publicador_de_revisao()
    achados = [
        Achado(
            "seguranca",
            Severidade.BLOQUEANTE,
            "veja ![](https://evil.test/?d=1) @dono",
            "src/a.py",
            3,
            Tier.ALTO,
        ),
        Achado("seguranca", Severidade.AVISO, "sem arquivo", None, None, Tier.BAIXO),
    ]
    assert await pub.check_run("a/b", SHA, "seguranca", achados, "r", "k") == "failure"
    assert await pub.check_run("a/b", SHA, "seguranca", achados, "r", "k") == "failure"
    assert len(cliente.checks) == 1  # a retentativa não duplica
    nome, conclusao, anotacoes = cliente.checks[0]
    assert nome == "forja/seguranca" and conclusao == "failure" and len(anotacoes) == 1
    assert anotacoes[0]["annotation_level"] == "failure" and anotacoes[0]["start_line"] == 3
    assert "://" not in anotacoes[0]["message"] and "@dono" not in anotacoes[0]["message"]
    assert await pub.check_run("a/b", SHA, "testes", [], "r", "k") == "success"
    with pytest.raises(ValueError, match="inválido"):
        await pub.check_run("a/b", "curto", "x", [], "r", "k")


async def test_merge_e_pr_pronto_so_com_destino_valido_idempotentes_e_em_dry_run_nao_escrevem() -> (
    None
):
    pub, cliente = _publicador_de_revisao()
    assert await pub.mesclar_pr("a/b", 7, SHA, "k") == "publicado"
    assert await pub.mesclar_pr("a/b", 7, SHA, "k") == "ja_publicado"
    assert await pub.marcar_pr_pronto("a/b", 7, "k") == "publicado"
    assert cliente.merges == [(7, SHA)] and cliente.prontos == [7]
    for args in (("../x", 7, SHA), ("a/b", 0, SHA), ("a/b", 7, "HEAD")):
        with pytest.raises(ValueError, match="inválido"):
            await pub.mesclar_pr(*args, "k2")
    seco, cliente2 = _publicador_de_revisao(dry_run=True)
    assert await seco.mesclar_pr("a/b", 7, SHA, "k") == "dry_run"
    assert await seco.marcar_pr_pronto("a/b", 7, "k") == "dry_run"
    assert await seco.check_run("a/b", SHA, "x", [], "r", "k") == "dry_run"
    assert (cliente2.merges, cliente2.prontos, cliente2.checks) == ([], [], [])


async def test_incidente_abre_issue_com_label_de_incidente_uma_vez_e_em_dry_run_nao_abre() -> None:
    pub, cliente = _publicador_de_revisao()
    url = await pub.abrir("a/b", "Incidente @dono ![](https://evil/?d=1)", "corpo @x", "k1")
    assert url == "https://github.test/issues/1" and len(cliente.issues) == 1
    titulo, corpo, rotulos = cliente.issues[0]
    assert rotulos == ["forja:incident"]  # nunca forja:intent: quem aplica é um humano
    assert "://" not in titulo and "@dono" not in titulo and "@x" not in corpo
    assert "ja_aberta" in await pub.abrir("a/b", "t", "c", "k1")  # a mesma chave não duplica
    assert len(cliente.issues) == 1
    seco, c2 = _publicador_de_revisao(dry_run=True)
    assert await seco.abrir("a/b", "t", "c", "k") == "dry-run" and not hasattr(c2, "issues")
    with pytest.raises(ValueError, match="inválido"):
        await pub.abrir("../x", "t", "c", "k2")
