"""Agente eco: roda dentro do sandbox e devolve o texto do Intent, sem lógica de negócio."""

from __future__ import annotations

from importlib import resources

from forja.application.portas.agente import (
    AgentRunner,
    LimitesSessao,
    PedidoAgente,
    RespostaDoAgente,
)
from forja.application.portas.sandbox import SandboxAtivo
from forja.infrastructure.agents.agent_sdk import AgentSdkRunner, ClienteSdk


def carregar_prompt_eco() -> str:
    return (
        resources.files("forja.infrastructure.agents").joinpath("prompts/eco.md").read_text("utf-8")
    )


class AgenteEco:
    def __init__(self, runner: AgentRunner, limites: LimitesSessao | None = None) -> None:
        self._runner = runner
        self._limites = limites or LimitesSessao()

    @classmethod
    def com_sdk(
        cls, cliente: ClienteSdk | None = None, limites: LimitesSessao | None = None
    ) -> AgenteEco:
        runner = (
            AgentSdkRunner(carregar_prompt_eco(), cliente)
            if cliente
            else AgentSdkRunner(carregar_prompt_eco())
        )
        return cls(runner, limites)

    async def executar(self, sandbox: SandboxAtivo, texto_do_intent: str) -> RespostaDoAgente:
        pedido = PedidoAgente(texto_do_intent, sandbox.worktree, self._limites)
        return await self._runner.executar(pedido)
