# pyright: basic
from pathlib import Path

import pytest

from forja.application.portas.sandbox import EspecSandbox, ResultadoComando, SandboxError
from forja.infrastructure.sandbox.docker import (
    ConfigDocker,
    DockerSandbox,
    _entregar_worktree,
    argumentos_run,
    usuario_efetivo,
)
from forja.infrastructure.sandbox.proxy_egress import (
    PoliticaEgress,
    RegistroBloqueios,
    configuracao_squid,
)
from forja.infrastructure.sandbox.worktree import GerenciadorWorktree


class DockerFalso:
    def __init__(self, falha_run: bool = False) -> None:
        self.chamadas: list[tuple[str, ...]] = []
        self.falha_run = falha_run

    async def __call__(self, *args: str, timeout_s: float = 60.0) -> ResultadoComando:
        self.chamadas.append(args)
        if args[0] == "run" and self.falha_run:
            return ResultadoComando(125, "", "boom")
        return ResultadoComando(0, "", "")


class GitFalso:
    def __init__(self) -> None:
        self.chamadas: list[tuple[str, ...]] = []

    async def __call__(self, *args: str, cwd: Path | None = None) -> str:
        self.chamadas.append(args)
        return ""


def montar(tmp_path, falha_run=False):
    docker, git = DockerFalso(falha_run), GitFalso()
    sb = DockerSandbox(GerenciadorWorktree(tmp_path / "wt", git), docker=docker)
    return sb, docker, git


async def test_ciclo_de_vida_cria_e_destroi_container_e_worktree(tmp_path):
    sb, docker, git = montar(tmp_path)
    ativo = await sb.criar(EspecSandbox("s1", str(tmp_path)))
    assert ativo.worktree == tmp_path / "wt" / "s1"
    assert git.chamadas[0][:3] == ("worktree", "add", "--detach")
    await sb.destruir("s1")
    assert docker.chamadas[-1] == ("rm", "-f", "forja-sbx-s1")
    assert any(c[:2] == ("worktree", "remove") for c in git.chamadas)


async def test_falha_no_run_nao_deixa_worktree(tmp_path):
    sb, docker, git = montar(tmp_path, falha_run=True)
    with pytest.raises(SandboxError):
        await sb.criar(EspecSandbox("s2", str(tmp_path)))
    assert docker.chamadas[-1][0] == "rm"
    assert any(c[:2] == ("worktree", "remove") for c in git.chamadas)


def test_container_sem_root_e_so_com_worktree_montado(tmp_path):
    args = argumentos_run(EspecSandbox("s3", "r"), tmp_path / "wt", ConfigDocker())
    uid, _, gid = args[args.index("--user") + 1].partition(":")
    assert uid != "0" and gid != "0"
    assert "--read-only" in args and "no-new-privileges" in args
    assert args[args.index("--cap-drop") + 1] == "ALL"
    montagens = [args[i + 1] for i, a in enumerate(args) if a == "-v"]
    assert montagens == [f"{tmp_path / 'wt'}:/workspace:rw"]


def test_segredos_do_host_nao_vazam_so_o_injetado(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "segredo-do-host")
    spec = EspecSandbox("s4", "r", ambiente_injetado={"DB_URL": "teste"})
    args = argumentos_run(spec, tmp_path, ConfigDocker())
    envs = [args[i + 1] for i, a in enumerate(args) if a == "-e"]
    assert "DB_URL=teste" in envs
    assert not any("segredo-do-host" in e or e.startswith("GITHUB_TOKEN") for e in envs)


def test_container_usa_rede_interna_e_proxy(tmp_path):
    args = argumentos_run(EspecSandbox("s5", "r"), tmp_path, ConfigDocker())
    assert args[args.index("--network") + 1] == "forja-sandbox-net"
    assert "HTTPS_PROXY=http://forja-egress-proxy:3128" in args


@pytest.mark.parametrize(
    ("host", "ok"),
    [
        ("api.anthropic.com", True),
        ("pypi.org", True),
        ("files.pythonhosted.org", True),
        ("evil.com", False),
        ("pypi.org.evil.com", False),
        ("notpypi.org", False),
    ],
)
def test_allowlist(host, ok):
    assert PoliticaEgress().permite(host) is ok


def test_bloqueios_sao_registrados_e_squid_nega_por_padrao():
    reg = RegistroBloqueios()
    reg.registrar("s1", "evil.com")
    assert reg.bloqueios == [("s1", "evil.com")]
    conf = configuracao_squid(PoliticaEgress())
    assert ".pypi.org" in conf and conf.index("allow permitidos") < conf.index("deny all")


def test_sessao_id_malicioso_e_recusado(tmp_path):
    with pytest.raises(SandboxError):
        GerenciadorWorktree(tmp_path).caminho("../etc")


def test_usuario_e_o_do_worktree_quando_nao_root_e_nunca_root(monkeypatch):
    monkeypatch.setattr("os.getuid", lambda: 1001)
    monkeypatch.setattr("os.getgid", lambda: 118)
    assert usuario_efetivo(ConfigDocker()) == "1001:118"
    monkeypatch.setattr("os.getuid", lambda: 0)
    assert usuario_efetivo(ConfigDocker()) == "10001:10001"
    assert usuario_efetivo(ConfigDocker(usuario="10001:10001")) == "10001:10001"


@pytest.mark.parametrize("u", ["0:0", "0", "root", "1000:0", "0:1000", "a:b", "10001:"])
def test_usuario_configurado_que_nao_e_uid_gid_sem_root_e_recusado(u):
    with pytest.raises(SandboxError):
        usuario_efetivo(ConfigDocker(usuario=u))


def test_entrega_do_worktree_nunca_toca_o_alvo_de_symlink(tmp_path, monkeypatch):
    fora = tmp_path / "fora"
    fora.mkdir()
    (fora / "shadow").write_text("x")
    wt = tmp_path / "wt"
    (wt / "sub").mkdir(parents=True)
    (wt / "real.txt").write_text("r")
    (wt / "link_arq").symlink_to(fora / "shadow")
    (wt / "link_dir").symlink_to(fora, target_is_directory=True)
    tocados: list[str] = []
    monkeypatch.setattr("os.getuid", lambda: 0)
    monkeypatch.setattr("os.lchown", lambda p, u, g: tocados.append(str(p)))
    monkeypatch.setattr("os.chown", lambda *a, **k: tocados.append("CHOWN"))
    _entregar_worktree(wt, "10001:10001")
    assert str(wt / "link_arq") in tocados and str(wt / "link_dir") in tocados
    assert "CHOWN" not in tocados
    assert not any(t.startswith(str(fora)) for t in tocados)
