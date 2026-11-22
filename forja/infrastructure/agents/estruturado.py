"""Agente que devolve JSON validado por schema: a única forma de saída de modelo que o
SDLC aceita. Uma reparação com o erro de validação; depois disso, falha explícita."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from forja.application.portas.agente import (
    AgenteError,
    AgentRunner,
    LimitesSessao,
    PedidoAgente,
    UsoModelo,
)
from forja.domain.erros import ErroDeDominio
from forja.infrastructure.telemetry.otel import registrar_uso, span_sessao_agente

_CERCA = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
TETO_DA_SAIDA = 60_000


class SaidaInvalida(AgenteError):
    """O modelo não produziu JSON que passe no schema, mesmo depois da reparação."""


def extrair_json(texto: str) -> Any:
    bruto = texto.strip()
    if len(bruto) > TETO_DA_SAIDA:
        raise ValueError("saída acima do teto")
    if (achado := _CERCA.match(bruto)) is not None:
        bruto = achado.group(1)
    inicio, fim = bruto.find("{"), bruto.rfind("}")
    if inicio < 0 or fim < inicio:
        raise ValueError("sem objeto JSON")
    return json.loads(bruto[inicio : fim + 1])


def somar(a: UsoModelo, b: UsoModelo) -> UsoModelo:
    return UsoModelo(
        a.tokens_entrada + b.tokens_entrada,
        a.tokens_saida + b.tokens_saida,
        a.custo_usd + b.custo_usd,
    )


class AgenteEstruturado[S: BaseModel]:
    def __init__(
        self, runner: AgentRunner, schema: type[S], papel: str, limites: LimitesSessao | None = None
    ) -> None:
        self._runner = runner
        self._schema = schema
        self._papel = papel
        self._limites = limites or LimitesSessao(timeout_s=300, max_turnos=3)

    async def pedir[T](
        self,
        intent_id: str,
        texto_nao_confiavel: str,
        converter: Callable[[S], T],
    ) -> tuple[T, UsoModelo]:
        """`converter` roda dentro da validação: erro de domínio dispara a reparação também."""
        uso = UsoModelo()
        erro = ""
        for tentativa in (1, 2):
            texto = texto_nao_confiavel
            if erro:
                texto += f"\n\n[resposta anterior recusada: {erro}. Responda só com JSON válido.]"
            with span_sessao_agente(
                intent_id, {"forja.papel": self._papel, "forja.tentativa": tentativa}
            ) as span:
                resp = await self._runner.executar(PedidoAgente(texto, limites=self._limites))
                registrar_uso(span, resp.uso)
            uso = somar(uso, resp.uso)
            try:
                return converter(self._schema.model_validate(extrair_json(resp.texto))), uso
            except (ValueError, ValidationError, ErroDeDominio) as exc:
                erro = type(exc).__name__ + ": " + str(exc)[:200].replace("\n", " ")
        raise SaidaInvalida(f"{self._papel}: saída fora do schema ({erro})")
