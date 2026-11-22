from collections.abc import Sequence

from forja.application.receber_intent import ReceberIntent
from forja.domain.eventos import EventoDeDominio, IntentRecebida
from forja.domain.intent import Intent, Origem, TipoDeOrigem


class IntentsEmMemoria:
    def __init__(self) -> None:
        self.dados: dict[str, Intent] = {}

    async def obter(self, intent_id: str) -> Intent | None:
        return self.dados.get(intent_id)

    async def salvar(self, intent: Intent) -> None:
        self.dados[intent.id] = intent


class PublicadorEmMemoria:
    def __init__(self) -> None:
        self.eventos: list[EventoDeDominio] = []

    async def publicar(self, eventos: Sequence[EventoDeDominio]) -> None:
        self.eventos += eventos


async def test_evento_repetido_nao_duplica_intent_nem_evento() -> None:
    intents, publicador = IntentsEmMemoria(), PublicadorEmMemoria()
    caso = ReceberIntent(intents, publicador)
    origem = Origem(TipoDeOrigem.ISSUE_GITHUB, "acme/loja", "42", "Corrigir login")
    primeira = await caso.executar(origem)
    segunda = await caso.executar(origem)
    assert primeira is segunda
    assert len(intents.dados) == 1
    assert [type(e) for e in publicador.eventos] == [IntentRecebida]
