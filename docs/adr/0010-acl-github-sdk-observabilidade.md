# 0010. ACL para GitHub, Agent SDK e backends de observabilidade (F-10)

- **Status:** Proposto
- **Data:** 2026-11-21
- **Id no design doc:** F-10 (seção 13; detalhe na seção 4.4)

## Contexto

O domínio (Intent, Entrega, Aprovacao, Politica) não deve conhecer payloads de webhook, REST e GraphQL do GitHub, tipos de mensagem do Claude Agent SDK nem o formato de Langfuse, Phoenix ou Prometheus. Esses formatos mudam e alguns backends ainda estão em aberto (Langfuse ou Phoenix).

## Decisão

GitHub (webhooks, REST e GraphQL), Claude Agent SDK (tipos de mensagem) e backends de observabilidade ficam atrás de tradutores na camada de infraestrutura (`infrastructure/github`, `infrastructure/agents`, `infrastructure/telemetry`). O domínio fala em Intent, Entrega, Aprovacao, nunca em `IssueCommentEvent` ou `ResultMessage`.

## Alternativas consideradas

- O design doc não registra alternativas para esta decisão. A preencher pelo autor antes de aceitar.

## Consequências

- Domínio testável em Python puro.
- Trocar backend de observabilidade ou versão do SDK fica contido num adaptador.
- Um tradutor por fronteira para manter, com testes de contrato.
