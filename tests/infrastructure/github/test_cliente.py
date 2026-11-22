# pyright: basic
from collections.abc import Callable
from typing import Any

import httpx
import pytest
import respx

from forja.infrastructure.github.cliente import (
    GitHubCliente,
    garantir_branch_de_trabalho,
    nome_da_branch,
)
from forja.infrastructure.github.erros import BranchProtegida

REPO = "acme-demo/loja-exemplo"


class AuthFalso:
    async def token_de_instalacao(self, repositorio: str) -> str:
        return "ghs_TOKEN_FICTICIO_DE_TESTE"


def test_nome_da_branch() -> None:
    assert nome_da_branch("abc", "corrige-login") == "forja/abc-corrige-login"
    assert nome_da_branch("abc", "Corrige o Login!") == "forja/abc-corrige-o-login"


def test_branch_padrao_ou_fora_do_prefixo_e_recusada() -> None:
    with pytest.raises(BranchProtegida):
        garantir_branch_de_trabalho("main", "main")
    with pytest.raises(BranchProtegida):
        garantir_branch_de_trabalho("release", "main")
    garantir_branch_de_trabalho("forja/abc-x", "main")


async def test_comenta_com_token_de_instalacao(fixture_json: Callable[[str], Any]) -> None:
    async with httpx.AsyncClient(base_url="https://api.github.com") as http:
        cliente = GitHubCliente(AuthFalso(), http)
        with respx.mock(base_url="https://api.github.com") as mock:
            rota = mock.post(f"/repos/{REPO}/issues/42/comments").respond(
                201, json=fixture_json("api_comment_created")
            )
            await cliente.comentar_issue(REPO, 42, "ok")

            assert (
                rota.calls.last.request.headers["authorization"]
                == "Bearer ghs_TOKEN_FICTICIO_DE_TESTE"
            )


async def test_cria_branch_a_partir_da_padrao(fixture_json: Callable[[str], Any]) -> None:
    async with httpx.AsyncClient(base_url="https://api.github.com") as http:
        cliente = GitHubCliente(AuthFalso(), http)
        with respx.mock(base_url="https://api.github.com") as mock:
            mock.get(f"/repos/{REPO}").respond(200, json=fixture_json("api_repo"))
            mock.get(f"/repos/{REPO}/git/ref/heads/main").respond(
                200, json=fixture_json("api_ref_main")
            )
            criar = mock.post(f"/repos/{REPO}/git/refs").respond(201, json={})

            assert (
                await cliente.criar_branch(REPO, "abc", "corrige-login")
                == "forja/abc-corrige-login"
            )
            corpo = criar.calls.last.request.content
            assert b"refs/heads/forja/abc-corrige-login" in corpo
            assert b"a1b2c3d4e5f60718293a4b5c6d7e8f9012345678" in corpo


async def test_recusa_branch_padrao_antes_de_escrever(fixture_json: Callable[[str], Any]) -> None:
    repo_padrao_forja = {**fixture_json("api_repo"), "default_branch": "forja/abc-x"}
    async with httpx.AsyncClient(base_url="https://api.github.com") as http:
        cliente = GitHubCliente(AuthFalso(), http)
        with respx.mock(base_url="https://api.github.com", assert_all_called=False) as mock:
            mock.get(f"/repos/{REPO}").respond(200, json=repo_padrao_forja)
            criar = mock.post(f"/repos/{REPO}/git/refs").respond(201, json={})

            with pytest.raises(BranchProtegida):
                await cliente.criar_branch(REPO, "abc", "x")
            assert criar.call_count == 0


async def test_permissao_de_escrita(fixture_json: Callable[[str], Any]) -> None:
    async with httpx.AsyncClient(base_url="https://api.github.com") as http:
        cliente = GitHubCliente(AuthFalso(), http)
        with respx.mock(base_url="https://api.github.com") as mock:
            mock.get(f"/repos/{REPO}/collaborators/maria-dev/permission").respond(
                200, json=fixture_json("api_permission_write")
            )
            mock.get(f"/repos/{REPO}/collaborators/leitor/permission").respond(
                200, json=fixture_json("api_permission_read")
            )
            mock.get(f"/repos/{REPO}/collaborators/estranho/permission").respond(404, json={})

            assert await cliente.tem_escrita(REPO, "maria-dev")
            assert not await cliente.tem_escrita(REPO, "leitor")
            assert not await cliente.tem_escrita(REPO, "estranho")


async def test_leitura_de_arquivo_distingue_ausencia_erro_e_tamanho_absurdo() -> None:
    import base64

    from forja.domain.artefatos import TETO_DE_ARTEFATO, ArtefatoInvalido
    from forja.infrastructure.github.erros import GitHubApiError

    url = f"/repos/{REPO}/contents/.forja/x/spec.md"
    async with httpx.AsyncClient(base_url="https://api.github.com") as http:
        cliente = GitHubCliente(AuthFalso(), http)
        with respx.mock(base_url="https://api.github.com") as mock:
            rota = mock.get(url)
            rota.respond(404)
            assert await cliente.ler_arquivo(REPO, "forja/x", ".forja/x/spec.md") is None
            rota.respond(500)
            with pytest.raises(GitHubApiError):
                await cliente.ler_arquivo(REPO, "forja/x", ".forja/x/spec.md")
            grande = base64.b64encode(b"a" * (TETO_DE_ARTEFATO + 1)).decode()
            rota.respond(200, json={"content": grande, "sha": "s", "size": TETO_DE_ARTEFATO + 1})
            with pytest.raises(ArtefatoInvalido):
                await cliente.ler_arquivo(REPO, "forja/x", ".forja/x/spec.md")
            ok = base64.b64encode(b"oi").decode()
            rota.respond(200, json={"content": ok, "sha": "s", "size": 2})
            assert await cliente.ler_arquivo(REPO, "forja/x", ".forja/x/spec.md") == "oi"


SHA = "c" * 40
REF = f"/repos/{REPO}/git/ref/heads/forja/x"


def _arq(nome, **extra):
    return {"filename": nome, "status": "modified", "additions": 1, "deletions": 0, **extra}


async def _com_github(rotas):
    http = httpx.AsyncClient(base_url="https://api.github.com")
    mock = respx.mock(base_url="https://api.github.com", assert_all_called=False)
    mock.start()
    mock.get(f"/repos/{REPO}").respond(200, json={"default_branch": "main"})
    for rota, resposta in rotas.items():
        mock.get(rota).respond(200, json=resposta)
    return GitHubCliente(AuthFalso(), http), mock, http


async def _fim(mock, http):
    mock.stop()
    await http.aclose()


async def test_diff_vem_da_ref_da_branch_e_nao_do_ultimo_commit_do_compare() -> None:
    cliente, mock, http = await _com_github(
        {
            REF: {"object": {"sha": SHA}},
            f"/repos/{REPO}/compare/main...{SHA}": {
                "files": [_arq("src/a.py", patch="+x" * 9000)],
                "commits": [{"sha": "1" * 40}],  # o compare só devolve até 250 commits
                "total_commits": 400,
            },
        }
    )
    try:
        d = await cliente.diff_da_entrega(REPO, "forja/x")
        assert d.head_sha == SHA and d.caminhos == ("src/a.py",) and not d.cortado
        assert len(d.arquivos[0].patch) <= 8000  # patch limitado
    finally:
        await _fim(mock, http)


async def test_compare_no_teto_de_300_arquivos_e_diff_cortado_e_rename_traz_a_origem() -> None:
    from forja.domain.politica import Politica, Tier
    from forja.domain.revisao import elevar_por_diff_incompleto

    arquivos = [_arq(f"docs/{i}.md") for i in range(299)] + [
        _arq("docs/main.tf", status="renamed", previous_filename="infra/main.tf")
    ]
    cliente, mock, http = await _com_github(
        {
            REF: {"object": {"sha": SHA}},
            f"/repos/{REPO}/compare/main...{SHA}": {"files": arquivos, "commits": []},
        }
    )
    try:
        d = await cliente.diff_da_entrega(REPO, "forja/x")
        assert d.cortado and "infra/main.tf" in d.caminhos  # o rename também mexeu em infra/
        p = Politica.de_dict(
            {"risk_tiers": {"high": {"paths": ["infra/**"]}, "low": {"paths": ["docs/**"]}}}
        )
        c = elevar_por_diff_incompleto(p.classificar(d.caminhos, [], 5), d)
        assert c.tier is Tier.ALTO and any("incompleto" in m for m in c.motivos)
    finally:
        await _fim(mock, http)


async def test_avanco_entre_dois_shas() -> None:
    a, b = "1" * 40, "2" * 40
    cliente, mock, http = await _com_github(
        {
            f"/repos/{REPO}/compare/{a}...{b}": {
                "total_commits": 1,
                "files": [{"filename": ".forja/x/review.md"}],
            }
        }
    )
    try:
        av = await cliente.avanco(REPO, a, b)
        assert av.so_o_review(".forja/x/review.md") and not av.so_o_review(".forja/y/review.md")
        assert (await cliente.avanco(REPO, a, a)).so_o_review("qualquer")  # nada mudou
    finally:
        await _fim(mock, http)


def _runs(*conclusoes, nome="ci/build", status="completed"):
    return [{"name": nome, "status": status, "conclusion": c} for c in conclusoes]


@pytest.mark.parametrize(
    ("runs", "statuses", "esperado"),
    [
        (_runs("success"), [], "verde"),
        (_runs("success", "neutral", "skipped"), [], "verde"),
        (_runs("startup_failure"), [], "falhou"),
        (_runs("stale"), [], "falhou"),
        (_runs("failure"), [], "falhou"),
        (_runs("success") + _runs("algo_novo"), [], "falhou"),  # fora da allowlist não é verde
        (_runs(None, status="in_progress"), [], "pendente"),
        (_runs("success", nome="forja/seguranca"), [], "sem_externos"),  # só a própria Forja
        (_runs("success", nome="forja/seguranca"), [{"state": "success"}], "verde"),
        ([], [], "sem_externos"),
        (_runs("success"), [{"state": "pending"}], "pendente"),
        (_runs("success"), [{"state": "failure"}], "falhou"),
        (_runs("success"), [{"state": "error"}], "falhou"),
    ],
)
async def test_checks_so_sao_verdes_pela_allowlist_com_check_externo_e_statuses(
    runs, statuses, esperado
) -> None:
    cliente, mock, http = await _com_github(
        {
            f"/repos/{REPO}/commits/{SHA}/check-runs": {
                "total_count": len(runs),
                "check_runs": runs,
            },
            f"/repos/{REPO}/commits/{SHA}/status": {"statuses": statuses},
        }
    )
    try:
        assert await cliente.estado_dos_checks(REPO, SHA) == esperado
    finally:
        await _fim(mock, http)


async def test_checks_paginam_e_o_que_nao_foi_lido_e_pendente() -> None:
    cliente, mock, http = await _com_github(
        {f"/repos/{REPO}/commits/{SHA}/status": {"statuses": []}}
    )
    try:
        rota = mock.get(f"/repos/{REPO}/commits/{SHA}/check-runs", params={"page": "1"})
        pagina1 = {"total_count": 140, "check_runs": _runs(*["success"] * 100, nome="forja/x")}
        rota.respond(200, json=pagina1)
        # a página 2 devolve vazio: 100 lidos de 140 é "não vi tudo"
        mock.get(f"/repos/{REPO}/commits/{SHA}/check-runs", params={"page": "2"}).respond(
            200, json={"total_count": 140, "check_runs": []}
        )
        assert await cliente.estado_dos_checks(REPO, SHA) == "pendente"
        mock.get(f"/repos/{REPO}/commits/{SHA}/check-runs", params={"page": "2"}).respond(
            200, json={"total_count": 140, "check_runs": _runs(*["success"] * 40)}
        )
        assert await cliente.estado_dos_checks(REPO, SHA) == "verde"  # leu as duas páginas
    finally:
        await _fim(mock, http)


async def test_statuses_paginam_e_o_estado_combinado_vale() -> None:
    sucesso = {"name": "ci", "status": "completed", "conclusion": "success"}
    cliente, mock, http = await _com_github(
        {f"/repos/{REPO}/commits/{SHA}/check-runs": {"total_count": 1, "check_runs": [sucesso]}}
    )
    rota = mock.get(f"/repos/{REPO}/commits/{SHA}/status", params={"page": "1"})
    pagina2 = mock.get(f"/repos/{REPO}/commits/{SHA}/status", params={"page": "2"})
    pagina2.respond(200, json={"state": "success", "total_count": 31, "statuses": []})
    try:
        trinta = [{"state": "success"}] * 30
        # 31 statuses: o 31º (página 2) falhou e o combinado também diz failure
        rota.respond(200, json={"state": "failure", "total_count": 31, "statuses": trinta})
        assert await cliente.estado_dos_checks(REPO, SHA) == "falhou"
        # o combinado diz success, mas só 30 de 31 foram servidos: não é verde
        rota.respond(200, json={"state": "success", "total_count": 31, "statuses": trinta})
        assert await cliente.estado_dos_checks(REPO, SHA) == "pendente"
        # o 31º, na página 2, falhou
        pagina2.respond(
            200, json={"state": "success", "total_count": 31, "statuses": [{"state": "failure"}]}
        )
        assert await cliente.estado_dos_checks(REPO, SHA) == "falhou"
        # sem nenhum status, `pending` do combinado não trava quem só usa check runs
        rota.respond(200, json={"state": "pending", "total_count": 0, "statuses": []})
        assert await cliente.estado_dos_checks(REPO, SHA) == "verde"
        # com statuses e combinado pending: pendente
        um = [{"state": "success"}]
        rota.respond(200, json={"state": "pending", "total_count": 1, "statuses": um})
        assert await cliente.estado_dos_checks(REPO, SHA) == "pendente"
    finally:
        await _fim(mock, http)


async def test_avanco_inclui_a_origem_de_um_rename() -> None:
    a, b = "1" * 40, "2" * 40
    cliente, mock, http = await _com_github(
        {
            f"/repos/{REPO}/compare/{a}...{b}": {
                "total_commits": 1,
                "files": [
                    {
                        "filename": ".forja/x/review.md",
                        "status": "renamed",
                        "previous_filename": "infra/a.tf",
                    }
                ],
            }
        }
    )
    try:
        av = await cliente.avanco(REPO, a, b)
        assert "infra/a.tf" in av.caminhos and not av.so_o_review(".forja/x/review.md")
    finally:
        await _fim(mock, http)


async def test_numero_do_pr_exige_destino_na_branch_padrao() -> None:
    cliente, mock, http = await _com_github({})
    rota = mock.get(f"/repos/{REPO}/pulls")
    try:
        rota.respond(200, json=[{"number": 9, "base": {"ref": "release"}}])
        assert await cliente.numero_do_pr(REPO, "forja/x") is None
        rota.respond(200, json=[{"number": 9}])  # sem base legível: não vale
        assert await cliente.numero_do_pr(REPO, "forja/x") is None
        rota.respond(
            200,
            json=[
                {"number": 9, "base": {"ref": "release"}},
                {"number": 4, "base": {"ref": "main"}},
            ],
        )
        assert await cliente.numero_do_pr(REPO, "forja/x") == 4
        assert "base=main" in str(rota.calls.last.request.url)
    finally:
        await _fim(mock, http)


async def test_politica_pr_pronto_e_merge_do_cliente() -> None:
    import base64

    from forja.domain.politica import Tier
    from forja.infrastructure.github.erros import GitHubApiError

    async with httpx.AsyncClient(base_url="https://api.github.com") as http:
        c = GitHubCliente(AuthFalso(), http)
        with respx.mock(base_url="https://api.github.com") as mock:
            mock.get(f"/repos/{REPO}").respond(200, json={"default_branch": "main"})
            politica = mock.get(f"/repos/{REPO}/contents/.forja/policy.yaml")
            ok = 'risk_tiers:\n  low:\n    paths: ["docs/**"]\n'
            conteudo = base64.b64encode(ok.encode()).decode()
            politica.respond(200, json={"content": conteudo, "sha": "s", "size": 40})
            assert (await c.politica(REPO)).classificar(["docs/a.md"], [], 1).tier is Tier.BAIXO
            politica.respond(404)
            assert not (await c.politica(REPO)).declarada  # ausente: fechada
            ruim = base64.b64encode(b"risk_tiers: {low: 1}").decode()  # fora do subconjunto
            politica.respond(200, json={"content": ruim, "sha": "s", "size": 10})
            assert (await c.politica(REPO)).classificar(["docs/a.md"], [], 1).tier is Tier.ALTO

            mock.get(f"/repos/{REPO}/pulls/7").respond(200, json={"node_id": "N7"})
            gql = mock.post("/graphql")
            gql.respond(200, json={"errors": [{"message": "x"}]})
            with pytest.raises(GitHubApiError):  # 200 com errors não é sucesso
                await c.marcar_pr_pronto(REPO, 7)
            gql.respond(200, json={"data": {}})
            await c.marcar_pr_pronto(REPO, 7)

            merge = mock.put(f"/repos/{REPO}/pulls/7/merge")
            merge.respond(200, json={"merged": False, "message": "x"})
            with pytest.raises(GitHubApiError):  # só merged:true é merge
                await c.mesclar_pr(REPO, 7, SHA)
            merge.respond(200, json={"merged": True})
            await c.mesclar_pr(REPO, 7, SHA)
