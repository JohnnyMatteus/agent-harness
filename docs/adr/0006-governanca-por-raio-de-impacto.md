# 0006. Governança por raio de impacto, aplicada por hooks e política como código (F-06)

- **Status:** Proposto
- **Data:** 2026-11-21
- **Id no design doc:** F-06 (seção 13; detalhe nas seções 9.1, 9.2 e 9.3)

## Contexto

O objetivo é o máximo de autonomia segura: mudanças de baixo risco podem seguir sozinhas, e código de alto risco (auth, pagamentos, migrações, infraestrutura) nunca dispensa humano (seção 2). Regras só no prompt podem ser ignoradas pelo modelo.

## Decisão

Cada repositório-alvo tem `.forja/policy.yaml` com tiers de risco (`high`, `medium`, `low`) por caminhos, labels e tamanho de diff, e orçamentos (`per_intent_usd`, `per_night_usd`, `max_sessions_per_intent`). O tier final é o maior entre caminhos tocados, labels e achados dos revisores. A política é aplicada no momento da ação por hooks do Claude Agent SDK (tabela da seção 9.2: `PreToolUse` em Write/Edit, Bash e ferramentas MCP de escrita no GitHub; `PostToolUse` para trace, custo e orçamento; fim de sessão exige `progress.md` atualizado e working tree limpo) e por permissões por etapa (seção 9.3). Auto-merge só em tier baixo, com checks verdes e auto-merge habilitado pelo dono.

## Alternativas consideradas

- Regras só por prompt: descartado ("aplicadas por hook, não só por prompt", seção 5.3).

## Consequências

- Regras verificáveis por eval de segurança (100% bloqueado, seção 11).
- Política de raio de impacto e hooks são núcleo do autor (modo par, seção 14).
- Cada repositório-alvo precisa manter a própria política.
