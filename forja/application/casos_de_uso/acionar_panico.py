from __future__ import annotations

import logging

from forja.application.portas.entregas import EntregaGateway

log = logging.getLogger(__name__)


class AcionarPanico:
    def __init__(self, entregas: EntregaGateway) -> None:
        self._entregas = entregas

    async def executar(self) -> int:
        cancelados = await self._entregas.cancelar_todas()
        log.warning("botão de pânico acionado", extra={"cancelados": cancelados})
        return cancelados
