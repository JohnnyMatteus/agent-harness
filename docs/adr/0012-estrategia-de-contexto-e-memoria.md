# 0012. Estratégia de contexto configurável por modelo, com context editing e memória por repositório (F-12)

- **Status:** Proposto
- **Data:** 2026-11-21
- **Id no design doc:** F-12 (seção 13; detalhe nas seções 3A e 6.4.2)

## Contexto

Contexto é recurso finito. Alguns modelos tendem a encerrar cedo perto do limite de contexto; sessões longas acumulam resultados de ferramentas antigos; erros se repetem entre sessões por falta de memória do projeto.

## Decisão

A estratégia de contexto é configurável por modelo: compactação automática numa sessão contínua, ou reset completo com handoff estruturado (`progress.md`, contrato, git log). Durante sessões longas, context editing remove resultados de ferramentas antigos. A Forja implementa o backend do memory tool: `/memories/<repo>/` em Postgres, com arquivos curtos de convenções, armadilhas, comandos que funcionam e decisões de revisão recorrentes; o Executor consulta no início e registra ao final, e o Avaliador registra padrões de defeito.

## Alternativas consideradas

- Compactação e reset são as duas opções do próprio design doc, mantidas como configuração por modelo.

## Consequências

- Menos tokens por funcionalidade e menos erros repetidos (métricas da seção 3A).
- A memória por repositório precisa de curadoria para não acumular informação errada.
