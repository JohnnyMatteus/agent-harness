# M1-11 · Trace ponta a ponta: OpenTelemetry, Langfuse e métricas do harness

- **core:** false
- **curso:** lt-tech-metrics
- **subagente:** devops + implementador
- **depende de:** M1-07, M1-10
- **estimativa:** 1 dia

## Objetivo

Instrumentar com OpenTelemetry o caminho webhook, workflow, activity, sessão do agente, de modo que uma entrega apareça como um único trace, com custo e tokens por sessão, e expor métricas básicas em Prometheus (seção 10.1).

## Critérios de aceite

```gherkin
Funcionalidade: Observabilidade do harness

  Cenário: Trace único
    Dado uma intenção processada do webhook ao eco
    Quando eu abro o trace no backend de observabilidade
    Então há spans encadeados de gateway, workflow, activity e sessão do agente com o mesmo trace id

  Cenário: Custo por sessão
    Dado uma sessão de agente concluída
    Quando o span da sessão é fechado
    Então ele traz tokens de entrada e saída e custo estimado

  Cenário: Métricas
    Dado o serviço rodando
    Quando eu consulto o endpoint de métricas
    Então vejo contadores de entregas iniciadas, concluídas e com erro

  Cenário: Backend trocável
    Dado a configuração do backend (Langfuse ou Phoenix)
    Quando eu troco um pelo outro
    Então nenhum código fora de "forja/infrastructure/telemetry" muda

  Cenário: Sem conteúdo sensível
    Dado spans e logs gerados
    Quando eu os inspeciono
    Então não contêm segredos nem tokens do GitHub
```

## Arquivos prováveis

- `forja/infrastructure/telemetry/otel.py`, `forja/infrastructure/telemetry/metricas.py`
- `docker-compose.yml` (coletor OTel, Langfuse ou Phoenix, Prometheus)
- `tests/infrastructure/telemetry/`

## Notas

- Langfuse ou Phoenix: o design doc deixa em aberto; o autor escolhe um para o compose do M1.
- Painel Grafana do harness fica para o M8; no M1 basta o trace e o endpoint de métricas.
