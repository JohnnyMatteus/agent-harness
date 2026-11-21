# 0007. GitHub App com permissões mínimas; o agente nunca publica direto, só o workflow (F-07)

- **Status:** Proposto
- **Data:** 2026-11-21
- **Id no design doc:** F-07 (seção 13; detalhe nas seções 8 e 9.4)

## Contexto

O harness escreve em repositórios reais (branches, PRs, checks, comentários). Texto de issues e PRs pode conter prompt injection (seção 9.4). Um token com permissão ampla nas mãos do agente transforma injeção em escrita.

## Decisão

A integração usa um GitHub App com permissões mínimas por repositório (contents, pull requests, issues, checks, metadata) e tokens de instalação de curta duração. Só o workflow publica PR, comentários e check runs; ferramentas MCP de escrita no GitHub são bloqueadas para o agente por hook. Branches seguem `forja/<intent-id>-<slug>` e nunca há escrita na branch padrão. Branch protection e CODEOWNERS são respeitados.

## Alternativas consideradas

- Token pessoal: descartado ("GitHub App (não token pessoal)", seção 8).

## Consequências

- Prompt injection não vira escrita externa sem passar pelo workflow.
- Configuração inicial do App (chave privada, instalação por repositório).
- Toda escrita no GitHub precisa ser modelada como passo de workflow.
