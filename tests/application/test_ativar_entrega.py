import pytest

from forja.application.casos_de_uso.acionar_panico import AcionarPanico
from forja.application.casos_de_uso.ativar_entrega import AtivarEntrega
from forja.application.comandos import (
    CriarIntent,
    Ignorado,
    OrigemExterna,
    Parar,
    ResultadoAtivacao,
    Sinalizacao,
)
from forja.application.portas.entregas import ResultadoInicio

ORIGEM = OrigemExterna("acme-demo/loja-exemplo", 42, "https://exemplo.test/issues/42")


class EntregasFalsas:
    def __init__(self) -> None:
        self.iniciadas: set[str] = set()
        self.paradas: list[str] = []
        self.sinais: list[Sinalizacao] = []
        self.em_andamento = 3

    async def iniciar(self, comando: CriarIntent) -> ResultadoInicio:
        if comando.origem.referencia in self.iniciadas:
            return "ja_existia"
        self.iniciadas.add(comando.origem.referencia)
        return "iniciada"

    async def sinalizar(self, comando: Sinalizacao) -> bool:
        self.sinais.append(comando)
        return comando.origem.referencia in self.iniciadas

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


async def test_repositorio_fora_da_lista_habilitada_e_ignorado_e_vazia_recusa_tudo() -> None:
    entregas = EntregasFalsas()
    permissoes = Permissoes({"maria"})
    habilitado = AtivarEntrega(entregas, permissoes, frozenset({"ACME-demo/loja-exemplo"}))
    assert await habilitado.executar(CRIAR) == "iniciada"
    outro = CriarIntent(OrigemExterna("acme-demo/outro", 1, "u"), "t", "c", "maria")
    assert await habilitado.executar(outro) == "ignorada"
    assert await AtivarEntrega(entregas, permissoes, frozenset()).executar(CRIAR) == "ignorada"


async def test_nome_de_repositorio_malformado_e_ignorado() -> None:
    ativar, entregas = caso()
    ruim = CriarIntent(OrigemExterna("../etc/passwd", 1, "u"), "t", "c", "maria")
    assert await ativar.executar(ruim) == "ignorada"
    assert not entregas.iniciadas


async def test_confirmacao_aprovacao_e_rejeicao_viram_sinais_so_de_quem_escreve() -> None:
    from forja.application.comandos import Aprovar, Confirmar, Rejeitar

    ativar, entregas = caso()
    await ativar.executar(CRIAR)
    for comando in (
        Confirmar(ORIGEM, "maria"),
        Aprovar(ORIGEM, "maria"),
        Rejeitar(ORIGEM, "maria", "x"),
    ):
        assert await ativar.executar(comando) == "sinalizada"
    assert len(entregas.sinais) == 3
    assert await ativar.executar(Aprovar(ORIGEM, "intruso")) == "ignorada"
    assert len(entregas.sinais) == 3
    sem_entrega = Confirmar(OrigemExterna("acme-demo/loja-exemplo", 99, "u"), "maria")
    assert await ativar.executar(sem_entrega) == "ignorada"
