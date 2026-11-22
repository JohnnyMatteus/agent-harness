"""Caso de uso: receber uma intenção. Eventos repetidos da mesma origem não duplicam a Intent."""

from forja.application.portas.eventos import PublicadorDeEventos, RepositorioDeIntents
from forja.domain.intent import Intent, Origem, intent_id_de


class ReceberIntent:
    def __init__(self, intents: RepositorioDeIntents, publicador: PublicadorDeEventos) -> None:
        self._intents = intents
        self._publicador = publicador

    async def executar(self, origem: Origem, criterios_de_sucesso: tuple[str, ...] = ()) -> Intent:
        existente = await self._intents.obter(intent_id_de(origem))
        if existente is not None:
            return existente
        intent = Intent.receber(origem, criterios_de_sucesso)
        await self._intents.salvar(intent)
        await self._publicador.publicar(intent.retirar_eventos())
        return intent
