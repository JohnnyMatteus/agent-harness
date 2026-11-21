# 0017. Multiagente orquestrador-trabalhadores só em pesquisa de spec e diagnóstico (F-17)

- **Status:** Proposto
- **Data:** 2026-11-21
- **Id no design doc:** F-17 (seção 13; detalhe nas seções 3A e 5.4)

## Contexto

Algumas tarefas são amplas e paralelizáveis (pesquisar código, ADRs, PRs, incidentes e métricas para escrever uma spec ou diagnosticar um incidente). Multiagente gasta bem mais tokens.

## Decisão

Spec e Diagnóstico usam um agente líder que dispara subagentes em paralelo (código, ADRs, PRs, incidentes, métricas) e um passo final de citação. Nas demais etapas, não há multiagente orquestrador-trabalhadores (os revisores paralelos do Review são paralelização simples, seção 5.4).

## Alternativas consideradas

- Multiagente em todas as etapas: descartado pelo custo de tokens (seção 3A).

## Consequências

- Qualidade da spec medida por rubrica contra o custo.
- A suíte de ablação verifica se o multiagente na spec continua justificando o custo.
