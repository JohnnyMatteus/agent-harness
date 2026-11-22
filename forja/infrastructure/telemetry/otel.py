"""OpenTelemetry: provider, spans de sessão com custo e redação de segredos.

O backend (Langfuse ou Phoenix) é só um endpoint OTLP configurável: trocar um pelo outro
muda configuração, não código fora deste pacote.
"""

from __future__ import annotations

import re
from collections.abc import Generator, Mapping
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Tracer

from forja.application.portas.agente import UsoModelo

NOME_TRACER = "forja"
_SEGREDO = re.compile(
    r"(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w+|sk-[A-Za-z0-9_-]{16,}|Bearer\s+\S+)"
)


def redigir(texto: str) -> str:
    return _SEGREDO.sub("[REDIGIDO]", texto)


def configurar_tracing(
    endpoint_otlp: str | None, servico: str = "forja", processors: list[SpanProcessor] | None = None
) -> TracerProvider:
    provider = TracerProvider(resource=Resource.create({"service.name": servico}))
    if endpoint_otlp:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint_otlp)))
    for p in processors or []:
        provider.add_span_processor(p)
    trace.set_tracer_provider(provider)
    return provider


def tracer() -> Tracer:
    return trace.get_tracer(NOME_TRACER)


def registrar_uso(span: Span, uso: UsoModelo, modelo: str | None = None) -> None:
    span.set_attribute("gen_ai.usage.input_tokens", uso.tokens_entrada)
    span.set_attribute("gen_ai.usage.output_tokens", uso.tokens_saida)
    span.set_attribute("forja.custo_estimado_usd", uso.custo_usd)
    if modelo:
        span.set_attribute("gen_ai.request.model", modelo)


@contextmanager
def span_sessao_agente(
    intent_id: str, atributos: Mapping[str, str | int] | None = None
) -> Generator[Span]:
    with tracer().start_as_current_span("agente.sessao") as span:
        span.set_attribute("forja.intent_id", intent_id)
        for k, v in (atributos or {}).items():
            span.set_attribute(k, redigir(v) if isinstance(v, str) else v)
        yield span


def interceptor_temporal():
    """Propaga o contexto de trace gateway -> workflow -> activity (um trace por entrega)."""
    from temporalio.contrib.opentelemetry import TracingInterceptor

    return TracingInterceptor()
