"""Avaliador independente (seção 5.3.1), com o loop conduzido pela Forja na Messages API.

Roda aqui, e não no Agent SDK, porque precisa de context editing (só existe na API) e do memory
tool nativo. Ferramentas: memória do repositório (backend próprio), comando de teste no sandbox
e leitura de arquivo, todas passando pelos guardrails de código. Não tem ferramenta de escrita.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, cast

from pydantic import BaseModel, ValidationError

from forja.application.casos_de_uso.memoria_do_repositorio import MemoriaDoRepositorio
from forja.application.portas.agente import AgenteError, UsoModelo
from forja.application.portas.harness import (
    Avaliacao,
    PedidoDeAvaliacao,
    RevisaoDoContrato,
)
from forja.application.portas.sandbox import SandboxAtivo
from forja.domain.guardrails import FERRAMENTA_EXEC, Etapa, PoliticaDeSessao, decidir_ferramenta
from forja.domain.harness import ContratoDeSprint
from forja.domain.seguranca import dado_nao_confiavel, redigir_segredos
from forja.infrastructure.agents.contexto import (
    BETA_CONTEXT_MANAGEMENT,
    EstrategiaDeContexto,
    context_management,
)
from forja.infrastructure.agents.esquemas import AvaliacaoSaida, RevisaoSaida
from forja.infrastructure.agents.estruturado import SaidaInvalida, somar
from forja.infrastructure.agents.sdlc import carregar_prompt
from forja.infrastructure.telemetry.otel import registrar_uso, span_sessao_agente

SAIDA_MAXIMA_DE_COMANDO = 4_000
ARQUIVO_MAXIMO = 20_000

FERRAMENTAS: list[dict[str, Any]] = [
    {"type": "memory_20250818", "name": "memory"},
    {
        "name": "executar_comando",
        "description": "Executa um comando no sandbox, sem shell. argv é a lista de argumentos.",
        "input_schema": {
            "type": "object",
            "properties": {"argv": {"type": "array", "items": {"type": "string"}}},
            "required": ["argv"],
        },
    },
    {
        "name": "ler_arquivo",
        "description": "Lê um arquivo do worktree.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
]
_OBJETO = {"type": "object", "additionalProperties": True}
FERRAMENTA_FINAL_AVALIACAO = {
    "name": "registrar_avaliacao",
    "description": "Encerra a avaliação: notas por critério (0 a 10), feedback e defeitos.",
    "input_schema": {
        **_OBJETO,
        "properties": {
            "notas": _OBJETO,
            "feedback": _OBJETO,
            "defeitos": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["notas"],
    },
}
FERRAMENTA_FINAL_REVISAO = {
    "name": "registrar_revisao",
    "description": "Encerra a revisão do contrato: acordo (bool) e ajustes pedidos.",
    "input_schema": {
        **_OBJETO,
        "properties": {
            "acordo": {"type": "boolean"},
            "ajustes": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["acordo"],
    },
}


class AvaliadorNaMessagesApi:
    def __init__(
        self,
        cliente: Any,
        modelo: str,
        memoria: Callable[[str], MemoriaDoRepositorio],
        contexto: EstrategiaDeContexto,
        *,
        preco_por_milhao: tuple[float, float],
        max_turnos: int = 16,
        max_tokens: int = 4096,
    ) -> None:
        """`preco_por_milhao` (entrada, saída, em USD) é obrigatório: custo desconhecido somaria
        zero e o orçamento por intenção mentiria."""
        if min(preco_por_milhao) <= 0:
            raise ValueError("preço por milhão de tokens deve ser positivo")
        self._cliente = cliente
        self._modelo = modelo
        self._memoria = memoria
        self._contexto = contexto
        self._max_turnos = max_turnos
        self._max_tokens = max_tokens
        self._preco = preco_por_milhao

    async def revisar_contrato(
        self, repositorio: str, contrato: ContratoDeSprint
    ) -> RevisaoDoContrato:
        texto = (
            f"<contrato>{dado_nao_confiavel(contrato.para_json())}</contrato>\n"
            "Revise: cada item é testável? A verificação cobre o entregável? "
            "Os limiares são rígidos o bastante?"
        )
        saida, uso = await self._rodar(
            repositorio,
            texto,
            FERRAMENTA_FINAL_REVISAO,
            RevisaoSaida,
            lambda s: s,
            None,
            "contrato",
        )
        return RevisaoDoContrato(saida.acordo, tuple(saida.ajustes), uso)

    async def avaliar(
        self, sandbox: SandboxAtivo, repositorio: str, pedido: PedidoDeAvaliacao
    ) -> Avaliacao:
        texto = (
            f"<contrato>{dado_nao_confiavel(pedido.contrato.para_json())}</contrato>\n"
            f"<intent>{dado_nao_confiavel(pedido.intent_md)}</intent>\n"
            f"<spec>{dado_nao_confiavel(pedido.spec_md)}</spec>\n"
            f"<plano>{dado_nao_confiavel(pedido.plano_md)}</plano>\n"
            f"<sessoes>{dado_nao_confiavel(pedido.resumo_das_sessoes)}</sessoes>\n"
            f"<testes_do_grader>{json.dumps(dict(pedido.resultados_dos_testes))}"
            "</testes_do_grader>\n"
            "Avalie o bloco contra o contrato."
        )
        (notas, feedback, defeitos), uso = await self._rodar(
            repositorio,
            texto,
            FERRAMENTA_FINAL_AVALIACAO,
            AvaliacaoSaida,
            lambda s: (*s.para_dominio(), tuple(s.defeitos)),
            sandbox,
            "avaliacao",
        )
        return Avaliacao(notas, feedback, defeitos, uso)

    async def _rodar[S: BaseModel, T](
        self,
        repositorio: str,
        texto: str,
        final: dict[str, Any],
        schema: type[S],
        converter: Callable[[S], T],
        sandbox: SandboxAtivo | None,
        papel: str,
    ) -> tuple[T, UsoModelo]:
        memoria = self._memoria(repositorio)
        politica = PoliticaDeSessao(Etapa.AVALIADOR, "0" * 16)
        ferramentas = [*FERRAMENTAS, final] if sandbox is not None else [FERRAMENTAS[0], final]
        sistema = carregar_prompt("avaliador")
        contexto_da_memoria = await memoria.para_o_prompt()
        mensagens: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": "<pedido_nao_confiavel>\n"
                f"{contexto_da_memoria}\n{texto}\n</pedido_nao_confiavel>",
            }
        ]
        uso = UsoModelo()
        for _ in range(self._max_turnos):
            with span_sessao_agente(repositorio, {"forja.papel": f"avaliador-{papel}"}) as span:
                resp = await self._cliente.beta.messages.create(
                    model=self._modelo,
                    max_tokens=self._max_tokens,
                    system=sistema,
                    messages=mensagens,
                    tools=ferramentas,
                    betas=[BETA_CONTEXT_MANAGEMENT],
                    context_management=context_management(self._contexto),
                )
                passo = self._uso(resp)
                registrar_uso(span, passo, self._modelo)
            uso = somar(uso, passo)
            blocos = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
            if not blocos:
                raise SaidaInvalida("avaliador encerrou sem chamar a ferramenta final")
            mensagens.append({"role": "assistant", "content": resp.content})
            resultados: list[dict[str, Any]] = []
            for b in blocos:
                if b.name == final["name"]:
                    try:
                        return converter(schema.model_validate(b.input)), uso
                    except (ValidationError, ValueError) as erro:
                        resultados.append(
                            _resultado(b.id, f"saída recusada: {str(erro)[:300]}", True)
                        )
                        continue
                resultados.append(
                    _resultado(b.id, *await self._ferramenta(b, memoria, politica, sandbox))
                )
            mensagens.append({"role": "user", "content": resultados})
        raise AgenteError(f"avaliador não concluiu em {self._max_turnos} turnos")

    def _uso(self, resp: Any) -> UsoModelo:
        entrada, saida = int(resp.usage.input_tokens), int(resp.usage.output_tokens)
        custo = (entrada * self._preco[0] + saida * self._preco[1]) / 1e6
        return UsoModelo(entrada, saida, custo)

    async def _ferramenta(
        self,
        bloco: Any,
        memoria: MemoriaDoRepositorio,
        politica: PoliticaDeSessao,
        sandbox: SandboxAtivo | None,
    ) -> tuple[str, bool]:
        bruto: Any = bloco.input
        entrada: dict[str, Any] = (
            {str(k): v for k, v in cast("dict[Any, Any]", bruto).items()}
            if isinstance(bruto, dict)
            else {}
        )
        if bloco.name == "memory":
            return await memoria.executar(entrada), False
        if sandbox is None:
            return "ferramenta indisponível nesta etapa", True
        executar: dict[str, Callable[[], Awaitable[str]]] = {
            "executar_comando": lambda: _comando(sandbox, politica, entrada),
            "ler_arquivo": lambda: _arquivo(sandbox, politica, entrada),
        }
        if bloco.name not in executar:
            return f"ferramenta desconhecida: {str(bloco.name)[:40]}", True
        try:
            return await executar[bloco.name](), False
        except PermissionError as erro:
            return f"bloqueado pelo guardrail: {erro}", True


def _resultado(id_: str, texto: str, erro: bool) -> dict[str, Any]:
    # Saída de comando e de arquivo é dado: segredos redigidos e tamanho limitado.
    return {
        "type": "tool_result",
        "tool_use_id": id_,
        "content": redigir_segredos(texto)[:SAIDA_MAXIMA_DE_COMANDO],
        "is_error": erro,
    }


async def _comando(
    sandbox: SandboxAtivo, politica: PoliticaDeSessao, entrada: dict[str, Any]
) -> str:
    d = decidir_ferramenta(politica, FERRAMENTA_EXEC, {"argv": entrada.get("argv")})
    if not d.permitido:
        raise PermissionError(d.motivo)
    r = await sandbox.executar([str(a) for a in entrada["argv"]], timeout_s=120)
    return f"saída {r.codigo_saida}\n{r.stdout[-SAIDA_MAXIMA_DE_COMANDO:]}\n{r.stderr[-1000:]}"


async def _arquivo(
    sandbox: SandboxAtivo, politica: PoliticaDeSessao, entrada: dict[str, Any]
) -> str:
    d = decidir_ferramenta(politica, "Read", {"file_path": entrada.get("path")})
    if not d.permitido:
        raise PermissionError(d.motivo)
    r = await sandbox.executar(["head", "-c", str(ARQUIVO_MAXIMO), str(entrada["path"])])
    return r.stdout if r.codigo_saida == 0 else f"erro ao ler: {r.stderr[-300:]}"
