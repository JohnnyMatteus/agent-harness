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

## Fixação do SHA e checks (falha fechada)

- A ponta da branch é lida da ref (o compare só devolve até 250 commits) e o diff é calculado por esse SHA. O SHA revisado é guardado; o único avanço aceito depois dele é o commit do `review.md` feito pela própria Forja (o compare revisado...atual deve ter zero commits ou um commit que só toca `.forja/<id>/review.md`). Esse SHA pós-review é fixado em `publicar_checks`, `estado_dos_checks` e `mesclar`; se a branch andou por outro motivo, a entrega falha para um humano. A aprovação humana vale só para esse SHA: se a branch andar entre o pedido e o clique, o PR não é marcado pronto. A chave de idempotência do merge inclui o SHA, e a activity de merge reconfere a ponta e os checks no momento.
- Check "verde" só com tudo concluído em `success`, `neutral` ou `skipped` (`startup_failure`, `stale` e conclusões desconhecidas falham), lendo todas as páginas (`total_count` maior que o lido é pendente) e os commit statuses (também paginados, com o `state` combinado e o `total_count`: failure ou error falham, status não lido por inteiro é pendente, e um combinado `pending` sem nenhum status não trava quem só usa check runs), e com ao menos um check externo (nome fora de `forja/`) ou status em sucesso: os check runs da própria Forja não provam nada sobre o CI do repositório. Sem check externo, não há auto-merge: a entrega vai para o portão humano.
- Diff incompleto: lista de arquivos no teto do compare é risco alto; patch truncado (8 000 caracteres por arquivo), arquivo sem patch (binário ou grande demais; só o rename puro escapa, porque os dois caminhos já são classificados), ou diff acima de 60 000 caracteres no prompt marcam a revisão como incompleta: no mínimo médio, logo nunca auto-merge, com o motivo no review.md.
- `carregar_politica` sem leitura configurada falha (não retentável) em vez de assumir orçamento ilimitado.
- O avanço da branch também conta a origem de um rename (`previous_filename`), então renomear de outro lugar para o `review.md` não passa por "só o review". `numero_do_pr` exige PR aberto com destino na branch padrão, e um `marcar_pronto` sem PR falha a entrega em vez de comentar "PR pronto".

## Limitações

- Auto-merge nunca rodou contra o GitHub real; os testes usam GitHub falso. CODEOWNERS e branch protection são respeitados só porque o merge falha se o GitHub recusar.
- A revisão é em um passo (sem rodar scanners externos nem testes de revisão no sandbox).
