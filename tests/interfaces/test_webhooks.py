from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import fakeredis
import httpx
import pytest
import pytest_asyncio

from forja.application.casos_de_uso.acionar_panico import AcionarPanico
from forja.application.casos_de_uso.ativar_entrega import AtivarEntrega
from forja.application.comandos import CriarIntent, OrigemExterna, Sinalizacao
from forja.application.portas.entregas import ResultadoInicio
from forja.infrastructure.github.assinatura import assinar
from forja.infrastructure.github.entregas_vistas import RegistroEntregasRedis
from forja.interfaces.http.app import criar_app
from forja.interfaces.http.panico import DependenciasPanico
from forja.interfaces.http.webhooks import ConfigWebhook, DependenciasWebhook

SEGREDO = "segredo-do-webhook"
LIMITE = 2048


class Entregas:
    def __init__(self) -> None:
        self.iniciadas: list[CriarIntent] = []
        self.falhar = False

    async def iniciar(self, comando: CriarIntent) -> ResultadoInicio:
        if self.falhar:
            raise RuntimeError("temporal fora")
        self.iniciadas.append(comando)
        return "iniciada"

    async def sinalizar(self, comando: Sinalizacao) -> bool:
        return True

    async def parar(self, origem: OrigemExterna) -> bool:
        return True

    async def cancelar_todas(self) -> int:
        return 0


class Permissoes:
    def __init__(self) -> None:
        self.escrita = True

    async def tem_escrita(self, repositorio: str, usuario: str) -> bool:
        return self.escrita


@dataclass
class Ambiente:
    cliente: httpx.AsyncClient
    entregas: Entregas
    permissoes: Permissoes


@pytest_asyncio.fixture
async def amb() -> AsyncIterator[Ambiente]:
    entregas, permissoes = Entregas(), Permissoes()
    registro = RegistroEntregasRedis(fakeredis.FakeAsyncRedis())
    app = criar_app(
        DependenciasWebhook(
            ConfigWebhook(SEGREDO, LIMITE), registro, AtivarEntrega(entregas, permissoes)
        ),
        DependenciasPanico("0" * 64, AcionarPanico(entregas)),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://forja"
    ) as cliente:
        yield Ambiente(cliente, entregas, permissoes)


def cabecalhos(
    corpo: bytes, entrega: str = "d-1", evento: str = "issues", assinatura: str | None = None
) -> dict[str, str]:
    return {
        "X-Hub-Signature-256": assinatura or assinar(SEGREDO, corpo),
        "X-GitHub-Event": evento,
        "X-GitHub-Delivery": entrega,
        "Content-Type": "application/json",
    }


async def test_assinatura_valida_aceita_e_segue_adiante(
    amb: Ambiente, fixture_bytes: Callable[[str], bytes]
) -> None:
    corpo = fixture_bytes("issues_labeled_forja_intent")
    resposta = await amb.cliente.post("/webhooks/github", content=corpo, headers=cabecalhos(corpo))

    assert resposta.status_code == 202
    assert resposta.json() == {"status": "iniciada"}
    assert len(amb.entregas.iniciadas) == 1


@pytest.mark.parametrize("assinatura", ["sha256=" + "0" * 64, None])
async def test_assinatura_invalida_ou_ausente_da_401(
    amb: Ambiente, fixture_bytes: Callable[[str], bytes], assinatura: str | None
) -> None:
    corpo = fixture_bytes("issues_labeled_forja_intent")
    cab = cabecalhos(corpo, assinatura=assinatura)
    if assinatura is None:
        del cab["X-Hub-Signature-256"]
    resposta = await amb.cliente.post("/webhooks/github", content=corpo, headers=cab)

    assert resposta.status_code == 401
    assert not amb.entregas.iniciadas


async def test_entrega_repetida_da_202_sem_reprocessar(
    amb: Ambiente, fixture_bytes: Callable[[str], bytes]
) -> None:
    corpo = fixture_bytes("issues_labeled_forja_intent")
    await amb.cliente.post("/webhooks/github", content=corpo, headers=cabecalhos(corpo))
    resposta = await amb.cliente.post("/webhooks/github", content=corpo, headers=cabecalhos(corpo))

    assert resposta.status_code == 202
    assert resposta.json() == {"status": "duplicada"}
    assert len(amb.entregas.iniciadas) == 1


async def test_autor_sem_escrita_e_ignorado(
    amb: Ambiente, fixture_bytes: Callable[[str], bytes]
) -> None:
    amb.permissoes.escrita = False
    corpo = fixture_bytes("issues_labeled_forja_intent")
    resposta = await amb.cliente.post("/webhooks/github", content=corpo, headers=cabecalhos(corpo))

    assert resposta.status_code == 202
    assert resposta.json() == {"status": "ignorada"}
    assert not amb.entregas.iniciadas


async def test_corpo_grande_da_413(amb: Ambiente) -> None:
    corpo = b"x" * (LIMITE + 1)
    resposta = await amb.cliente.post("/webhooks/github", content=corpo, headers=cabecalhos(corpo))
    assert resposta.status_code == 413


async def test_json_invalido_da_400(amb: Ambiente) -> None:
    corpo = b"nao e json"
    resposta = await amb.cliente.post("/webhooks/github", content=corpo, headers=cabecalhos(corpo))
    assert resposta.status_code == 400


async def test_falha_no_processamento_libera_o_reenvio(
    amb: Ambiente, fixture_bytes: Callable[[str], bytes]
) -> None:
    corpo = fixture_bytes("issues_labeled_forja_intent")
    amb.entregas.falhar = True
    falha = await amb.cliente.post("/webhooks/github", content=corpo, headers=cabecalhos(corpo))
    amb.entregas.falhar = False
    reenvio = await amb.cliente.post("/webhooks/github", content=corpo, headers=cabecalhos(corpo))

    assert falha.status_code == 500
    assert reenvio.json() == {"status": "iniciada"}
