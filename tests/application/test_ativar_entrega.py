import pytest

from forja.application.casos_de_uso.acionar_panico import AcionarPanico
from forja.application.casos_de_uso.ativar_entrega import AtivarEntrega
from forja.application.comandos import (
    CriarIntent,
    Ignorado,
    OrigemExterna,
    Parar,
    ResultadoAtivacao,
)
from forja.application.portas.entregas import ResultadoInicio

ORIGEM = OrigemExterna("acme-demo/loja-exemplo", 42, "https://exemplo.test/issues/42")


class EntregasFalsas:
    def __init__(self) -> None:
        self.iniciadas: set[str] = set()
        self.paradas: list[str] = []
        self.em_andamento = 3

    async def iniciar(self, comando: CriarIntent) -> ResultadoInicio:
        if comando.origem.referencia in self.iniciadas:
            return "ja_existia"
        self.iniciadas.add(comando.origem.referencia)
        return "iniciada"

    async def parar(self, origem: OrigemExterna) -> bool:
        if origem.referencia not in self.iniciadas:
            return False
        self.paradas.append(origem.referencia)
        return True

    async def cancelar_todas(self) -> int:
        cancelados, self.em_andamento = self.em_andamento, 0
        return cancelados


class Permissoes:
    def __init__(self, escritores: set[str]) -> None:
        self.escritores = escritores

    async def tem_escrita(self, repositorio: str, usuario: str) -> bool:
        return usuario in self.escritores


def caso(escritores: set[str] | None = None) -> tuple[AtivarEntrega, EntregasFalsas]:
    entregas = EntregasFalsas()
    return AtivarEntrega(
        entregas, Permissoes({"maria"} if escritores is None else escritores)
    ), entregas


CRIAR = CriarIntent(ORIGEM, "t", "c", "maria")


async def test_label_inicia_e_repeticao_nao_duplica() -> None:
    ativar, _ = caso()

    assert await ativar.executar(CRIAR) == "iniciada"
    assert await ativar.executar(CRIAR) == "ja_existia"


async def test_parar_de_quem_escreve_sinaliza() -> None:
    ativar, entregas = caso()
    await ativar.executar(CRIAR)

    assert await ativar.executar(Parar(ORIGEM, "maria")) == "sinalizada"
    assert entregas.paradas == [ORIGEM.referencia]


async def test_parar_sem_entrega_e_ignorado() -> None:
    ativar, _ = caso()
    assert await ativar.executar(Parar(ORIGEM, "maria")) == "ignorada"


@pytest.mark.parametrize("comando", [CRIAR, Parar(ORIGEM, "intruso")])
async def test_sem_permissao_de_escrita_nao_dispara(comando: CriarIntent | Parar) -> None:
    ativar, entregas = caso(escritores=set())
    resultado: ResultadoAtivacao = await ativar.executar(comando)

    assert resultado == "ignorada"
    assert not entregas.iniciadas


async def test_ignorado_nao_chama_nada() -> None:
    ativar, entregas = caso()
    assert await ativar.executar(Ignorado("x")) == "ignorada"
    assert not entregas.iniciadas


async def test_panico_cancela_todas() -> None:
    entregas = EntregasFalsas()
    assert await AcionarPanico(entregas).executar() == 3
    assert entregas.em_andamento == 0
