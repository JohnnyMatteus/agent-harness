# pyright: basic
import pytest

from forja.domain.bandas import BandasInvalidas
from forja.infrastructure.telemetry.bandas_do_operador import BandasDoOperador

DOC = (
    "service: loja\nbands:\n  - id: lat\n"
    '    query: "histogram_quantile(0.95, x)"\n    max: 0.3\n    for: 5m\n'
)


async def test_le_as_bandas_do_arquivo_do_operador_por_repositorio(tmp_path) -> None:
    (tmp_path / "acme__loja.yaml").write_text(DOC, encoding="utf-8")
    b = await BandasDoOperador(tmp_path).bandas("acme/loja")
    assert b is not None and b.bandas[0].consulta == "histogram_quantile(0.95, x)"
    assert await BandasDoOperador(tmp_path).bandas("acme/outro") is None  # sem arquivo: nada


async def test_repositorio_hostil_nao_escolhe_arquivo_fora_do_diretorio(tmp_path) -> None:
    fora = tmp_path / "segredo.yaml"
    fora.write_text(DOC, encoding="utf-8")
    pasta = tmp_path / "bandas"
    pasta.mkdir()
    for nome in ("../segredo", "a/b/c", "a/..", "", "a b/c"):
        with pytest.raises(BandasInvalidas):
            await BandasDoOperador(pasta).bandas(nome)
    (pasta / "acme__loja.yaml").symlink_to(fora)  # symlink não é seguido
    assert await BandasDoOperador(pasta).bandas("acme/loja") is None


async def test_arquivo_invalido_ou_gigante_e_recusado_nao_ignorado(tmp_path) -> None:
    (tmp_path / "acme__loja.yaml").write_text("service: x\nbands: []\nextra: 1\n", encoding="utf-8")
    with pytest.raises(BandasInvalidas):
        await BandasDoOperador(tmp_path).bandas("acme/loja")
    (tmp_path / "acme__grande.yaml").write_text("#" * (65 * 1024), encoding="utf-8")
    with pytest.raises(BandasInvalidas, match="teto"):
        await BandasDoOperador(tmp_path).bandas("acme/grande")
