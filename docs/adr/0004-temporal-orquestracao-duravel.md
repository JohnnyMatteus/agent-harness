# 0004. Temporal para orquestração durável e sinais de aprovação (F-04)

- **Status:** Proposto
- **Data:** 2026-11-21
- **Id no design doc:** F-04 (seção 13; detalhe na seção 7.1)

## Contexto

Uma entrega pode durar horas ou dias, esperar aprovação humana e atravessar reinícios do servidor. Eventos repetidos do GitHub não podem gerar execuções duplicadas.

## Decisão

As entregas são workflows do Temporal (Python SDK): o Temporal guarda o estado, refaz activities que falham, tem timers ("se ninguém aprovar em 48 h, lembrar e depois pausar") e recebe sinais externos (aprovação, cancelamento). Cada sessão de agente é uma activity com timeout e heartbeat. Há um workflow por intenção, com id determinístico; eventos repetidos viram sinais, nunca execuções duplicadas. Workflows previstos: `DeliveryWorkflow`, `ReviewWorkflow`, `NightlyWorkflow`, `IncidentWorkflow`.

## Alternativas consideradas

- O design doc não registra alternativas para esta decisão. A preencher pelo autor antes de aceitar.

## Consequências

- Durabilidade, retentativas e espera por humano sem código próprio de agendamento.
- Mais um serviço para operar (servidor Temporal), mitigado pelo `docker compose` único de desenvolvimento (seção 15).
- Código de workflow precisa ser determinístico; chamadas de modelo e de GitHub ficam em activities.
