"""Executor das etapas do SDLC (M3): despacha a etapa para o agente certo."""

from __future__ import annotations

from forja.application.portas.agente import UsoModelo
from forja.application.portas.sdlc import Especificador, Interprete, Pedido, Planejador
from forja.infrastructure.temporal.activities import EtapaEntrada, EtapaSaida


def _saida(etapa: str, resumo: str, texto: str, uso: UsoModelo, pontos: int = 0) -> EtapaSaida:
    return EtapaSaida(
        etapa, resumo, texto, pontos, uso.tokens_entrada, uso.tokens_saida, uso.custo_usd
    )


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
                r = await self._interprete.interpretar(pedido)
                return _saida("plan", "intent", r.valor.renderizar(), r.uso)
            case "design":
                r = await self._especificador.especificar(
                    entrada.repositorio, self._exigir(entrada, "intent.md")
                )
                return _saida(
                    "design", "spec", r.valor.renderizar(), r.uso, len(r.valor.pontos_em_aberto)
                )
            case "build":
                r = await self._planejador.planejar(
                    entrada.repositorio,
                    self._exigir(entrada, "intent.md"),
                    self._exigir(entrada, "spec.md"),
                )
                return _saida("build", "plano", r.valor.renderizar(), r.uso)
            case _:
                raise ValueError(f"etapa sem executor: {entrada.etapa[:40]}")

    @staticmethod
    def _exigir(entrada: EtapaEntrada, nome: str) -> str:
        texto = entrada.artefatos.get(nome)
        if not texto:
            raise ValueError(f"artefato {nome} ausente para a etapa {entrada.etapa}")
        return texto
