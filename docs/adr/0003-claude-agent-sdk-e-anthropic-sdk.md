# 0003. Claude Agent SDK para agentes; SDK anthropic direto para etapas de workflow simples (F-03)

- **Status:** Proposto
- **Data:** 2026-11-21
- **Id no design doc:** F-03 (seção 13; detalhe nas seções 4.3 e 5.4)

## Contexto

Algumas etapas precisam de loop de agente com ferramentas, hooks, subagentes, MCP e permissões (Executor, Spec, Diagnóstico); outras são chamadas simples de modelo (roteamento, classificação). O princípio é começar pelo padrão mais simples e usar agente só onde há exploração (seção 3).

## Decisão

Agentes usam o `claude-agent-sdk` (Python), que traz loop, ferramentas, hooks, subagentes, MCP e permissões. Etapas de workflow simples (roteamento, classificação) chamam o modelo pelo SDK `anthropic` direto, sem o loop completo. Os tipos de mensagem do Agent SDK ficam atrás da ACL (ADR 0010).

## Alternativas consideradas

- Agente em todas as etapas: contraria o princípio "comece pelo workflow mais simples" (seções 3 e 3A, Building effective agents).

## Consequências

- Menos custo e menos variância nas etapas simples.
- Dois clientes de modelo para manter e instrumentar (custo e trace nos dois).
- Acoplamento a um fornecedor de modelo, mitigado pela ACL.
