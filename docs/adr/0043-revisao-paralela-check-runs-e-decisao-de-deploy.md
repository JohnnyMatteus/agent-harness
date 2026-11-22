# 0043. Revisão paralela, check runs, auto-merge por tier e orçamento

- **Status:** Proposto
- **Data:** 2026-11-22
- **Id no design doc:** seções 5.1, 5.2 (Deploy), 8 e 9.1; M5

## Decisão

- **Revisores:** segurança, testes, ADRs e desempenho, quatro agentes sem ferramenta em paralelo (`asyncio.gather`); o diff chega por código, delimitado como dado. Achado só vale apontando para arquivo do diff e linha plausível (inventado é recusado com uma reparação). Verificações determinísticas não dependem do modelo: scanner de segredos (bloqueante, risco alto) e "código sem teste". Um revisor que falha derruba a revisão: não há aprovação por omissão.
- **review.md** renderizado por código e commitado antes dos check runs; um **check run por revisor** no commit atual da branch, com anotações por linha neutralizadas; criação idempotente e em dry-run por padrão.
- **Decisão:** achado bloqueante leva Review para Build e a entrega falha para um humano (sem laço automático de correção, limitação registrada). Sem bloqueante: tier baixo, política permitindo e o repositório em `FORJA_AUTOMERGE_REPOS` (a pessoa dona habilita) vão para Deploy e o auto-merge espera checks verdes (até 12 verificações de 5 min), marca o PR pronto (GraphQL, com `errors` tratado como falha) e mescla com `sha` e squash, só aceitando `merged: true`. Médio e alto abrem o portão humano (`/forja approve` ou `/forja reject`): aprovar marca o PR pronto e termina com "aprovada"; o merge é humano. Rejeitar termina como rejeitada (ADR 0038).
- **Orçamento:** `per_intent_usd` e `max_sessions_per_intent` do `policy.yaml` são checados antes de cada bloco e da revisão; estourar interrompe a entrega para um humano. `per_night_usd` é do NightlyWorkflow (fora do escopo até hoje).
- **Custo do Avaliador:** exige preço configurado, senão o orçamento mentiria (ADR 0041).

## Limitações

- Auto-merge nunca rodou contra o GitHub real; os testes usam GitHub falso. CODEOWNERS e branch protection são respeitados só porque o merge falha se o GitHub recusar.
- A revisão é em um passo (sem rodar scanners externos nem testes de revisão no sandbox).
