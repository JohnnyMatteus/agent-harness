"""Métricas Prometheus do harness (seção 10.1). Registry próprio facilita testes."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, generate_latest

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


class MetricasForja:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        self.iniciadas = Counter(
            "forja_entregas_iniciadas_total", "Entregas iniciadas", registry=self.registry
        )
        self.concluidas = Counter(
            "forja_entregas_concluidas_total", "Entregas concluídas", registry=self.registry
        )
        self.com_erro = Counter(
            "forja_entregas_erro_total", "Entregas com erro", registry=self.registry
        )
        self.bloqueios_egress = Counter(
            "forja_sandbox_egress_bloqueios_total",
            "Conexões de saída bloqueadas",
            registry=self.registry,
        )
        self.custo_usd = Counter(
            "forja_custo_usd_total", "Custo estimado de sessões", registry=self.registry
        )

        self.bloqueios = Counter(
            "forja_bloqueios_hook_total",
            "Ações de agente bloqueadas por guardrail",
            ["origem"],
            registry=self.registry,
        )
        self.tokens = Counter(
            "forja_tokens_total", "Tokens das sessões", ["direcao"], registry=self.registry
        )

        # Maintain (M6): o que o monitor não conseguiu ver e o que o diagnóstico custou.
        self.bandas_sem_dados = Counter(
            "forja_bandas_sem_dados_total",
            "Verificações de banda sem dado confiável (não é violação nem saudável)",
            registry=self.registry,
        )
        self.diagnosticos = Counter(
            "forja_diagnosticos_total", "Diagnósticos de incidente pagos", registry=self.registry
        )

    def exportar(self) -> bytes:
        return generate_latest(self.registry)
