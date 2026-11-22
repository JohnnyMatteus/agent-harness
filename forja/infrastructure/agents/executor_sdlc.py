"""Executor das etapas do SDLC (M3): despacha a etapa para o agente certo."""

from __future__ import annotations

from forja.application.portas.sdlc import Especificador, Interprete, Pedido, Planejador
from forja.infrastructure.temporal.activities import EtapaEntrada, EtapaSaida


class ExecutorSdlc:
    def __init__(
        self, interprete: Interprete, especificador: Especificador, planejador: Planejador
    ) -> None:
        self._interprete = interprete
        self._especificador = especificador
        self._planejador = planejador

    async def __call__(self, entrada: EtapaEntrada) -> EtapaSaida:
        if not entrada.repositorio:
            raise ValueError("etapa sem repositório")
        match entrada.etapa:
            case "plan":
                pedido = Pedido(
                    entrada.repositorio,
                    entrada.numero,
                    entrada.titulo,
                    entrada.corpo,
                    entrada.url or None,
                )
                intent = (await self._interprete.interpretar(pedido)).valor
                return EtapaSaida("plan", "intent", intent.renderizar())
            case "design":
                spec = (
                    await self._especificador.especificar(
                        entrada.repositorio, self._exigir(entrada, "intent.md")
                    )
                ).valor
                return EtapaSaida("design", "spec", spec.renderizar(), len(spec.pontos_em_aberto))
            case "build":
                plano = (
                    await self._planejador.planejar(
                        entrada.repositorio,
                        self._exigir(entrada, "intent.md"),
                        self._exigir(entrada, "spec.md"),
                    )
                ).valor
                return EtapaSaida("build", "plano", plano.renderizar())
            case _:
                raise ValueError(f"etapa sem executor: {entrada.etapa[:40]}")

    @staticmethod
    def _exigir(entrada: EtapaEntrada, nome: str) -> str:
        texto = entrada.artefatos.get(nome)
        if not texto:
            raise ValueError(f"artefato {nome} ausente para a etapa {entrada.etapa}")
        return texto
