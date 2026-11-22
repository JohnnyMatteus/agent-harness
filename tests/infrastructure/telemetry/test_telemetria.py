# pyright: basic
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from forja.application.portas.agente import UsoModelo
from forja.infrastructure.telemetry.metricas import MetricasForja
from forja.infrastructure.telemetry.otel import redigir, registrar_uso, span_sessao_agente


def provider_em_memoria(monkeypatch):
    exp = InMemorySpanExporter()
    prov = TracerProvider()
    prov.add_span_processor(SimpleSpanProcessor(exp))
    monkeypatch.setattr(
        "forja.infrastructure.telemetry.otel.trace.get_tracer", lambda n: prov.get_tracer(n)
    )
    return exp, prov


def test_span_da_sessao_traz_tokens_e_custo(monkeypatch):
    exp, _ = provider_em_memoria(monkeypatch)
    with span_sessao_agente("abc") as span:
        registrar_uso(span, UsoModelo(10, 5, 0.02))
    attrs = exp.get_finished_spans()[0].attributes
    assert attrs is not None
    assert attrs["gen_ai.usage.input_tokens"] == 10
    assert attrs["gen_ai.usage.output_tokens"] == 5
    assert attrs["forja.custo_estimado_usd"] == 0.02


def test_spans_encadeados_compartilham_trace_id(monkeypatch):
    exp, prov = provider_em_memoria(monkeypatch)
    with prov.get_tracer("t").start_as_current_span("workflow"), span_sessao_agente("abc"):
        pass
    a, b = exp.get_finished_spans()
    assert a.context is not None and b.context is not None
    assert a.context.trace_id == b.context.trace_id


def test_segredos_sao_redigidos(monkeypatch):
    exp, _ = provider_em_memoria(monkeypatch)
    with span_sessao_agente("abc", {"cabecalho": "Bearer abc123 ghp_" + "a" * 30}):
        pass
    attrs = exp.get_finished_spans()[0].attributes
    assert (
        attrs is not None
        and "ghp_" not in str(attrs["cabecalho"])
        and "abc123" not in str(attrs["cabecalho"])
    )
    assert redigir("ok") == "ok"


def test_metricas_de_entregas():
    m = MetricasForja()
    m.iniciadas.inc()
    m.concluidas.inc()
    m.com_erro.inc()
    saida = m.exportar().decode()
    for nome in ("iniciadas", "concluidas", "erro"):
        assert f"forja_entregas_{nome}_total 1.0" in saida
