# 0008. Sandbox efêmero por sessão com egress em allowlist; segredos fora do contexto (F-08)

- **Status:** Proposto
- **Data:** 2026-11-21
- **Id no design doc:** F-08 (seção 13; detalhe nas seções 4.3 e 9.4)

## Contexto

O Executor roda comandos arbitrários (build, testes, scripts) em código de terceiros e pode ser alvo de prompt injection. Segredos no contexto do modelo podem vazar em transcrições, PRs ou chamadas de rede.

## Decisão

Cada sessão de agente roda num container efêmero (Docker rootless, gVisor opcional) com um git worktree próprio, usuário sem root e sistema de arquivos restrito ao worktree. A saída de rede só alcança registries de pacotes e a API do modelo (allowlist). Segredos nunca entram no contexto do modelo; são injetados só nos passos de teste que precisam, via Vault. `/forja stop` e o botão de pânico destroem sandboxes.

## Alternativas consideradas

- O design doc deixa duas implementações em aberto: runtime de sandbox da Anthropic (bubblewrap + proxy de rede) ou container rootless com proxy de saída por allowlist (seção 9.4). Ver ADR 0016.

## Consequências

- Uma sessão comprometida não alcança outros worktrees, segredos nem destinos arbitrários de rede.
- Custo de criar e destruir container por sessão.
- Dependências fora da allowlist precisam ser liberadas explicitamente.
