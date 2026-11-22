# 0047. Evals do M8: regressão determinística do harness, camada com modelo real desligada

- **Status:** Proposto; implementação parcial (ver "Não feito")
- **Data:** 2026-11-22
- **Id no design doc:** F-09 e F-18 (ADR 0018), seção 11 e M8

## Decisão

- **O que existe é regressão determinística do harness, não avaliação de agente.** Um eval confere o RESULTADO no ambiente (tier calculado, estado devolvido, decisão do hook, o que foi mesclado), nunca o texto de um agente. Sem modelo, as taxas medem só o código de produção. Todo relatório (`forja.domain.avaliacao.Relatorio`) carrega o executor que rodou e, com executor falso ou nenhum, imprime o aviso de que isso não é qualidade de agente; taxa, pass@k ou ablação com modelo falso nunca são apresentados como qualidade.
- **Evals de segurança** (`tests/evals/seguranca/`, marcador `eval_regressao`): 15 casos tirados de falhas reais já corrigidas (M3: caminho vindo de modelo, saída não confiável; M4: allowlist do hook do Executor; M5: glob de segmento, caminho longo, `.github`/`.forja`, rename, arquivo sem patch, avanço por rename, allowlist de conclusões, statuses paginados, SHA fixado no merge; M6: `sem_dados`, `max` não finito, lista de repositórios do operador). Cada caso chama o ponto de entrada de produção e tem um caso de "agir" além dos de "recusar" quando faz sentido. Para cada um há um segundo teste que reintroduz o defeito original por mutação (monkeypatch) e exige que o caso FALHE com `AssertionError` do próprio grader: a prova de que o eval enxerga a proteção. Um erro do eval (rota inesperada, exceção) não conta como "falhou".
- **pass@k e pass^k** são calculados por código (`pass_at_k`, `pass_hat_k`, estimadores combinatórios não viesados) com testes de valores conhecidos e propriedades (hypothesis).
- **Gate de CI:** `infra/ci/verificar_evals.py` lê o JUnit do pytest e falha se zero testes rodaram, se há qualquer falha, erro ou skip, ou se rodaram menos que o mínimo. O job `evals-regressao` roda só `-m eval_regressao`, com `permissions: contents: read`, sem secrets e sem `pull_request_target`.
- **Camada com modelo real:** manual, desligada e sem implementação (`python -m forja.interfaces.cli.evals_reais`). Sem `FORJA_EVAL_MODELO_REAL=true`, `ANTHROPIC_API_KEY`, `FORJA_EVAL_MODELO`, `FORJA_EVAL_RUBRICA` e `FORJA_EVAL_LIMIAR` sai com erro 2 e lista o que falta; com tudo configurado sai com 3 ("não implementada: decisões do autor"). Nunca sai 0, lê só o ambiente do processo (nunca `.env`), não cria segredo e não chama API.
- **Painel:** `infra/observabilidade/painel-forja.json` (Grafana) usa só métricas que `/metrics` exporta hoje (entregas, custo, tokens, bloqueios, `sem_dados`, diagnósticos); um teste confere que cada métrica do JSON existe. Não há painel de pass@k nem de qualidade, porque isso não é exportado. O painel não foi aberto num Grafana real.

## Não feito (e por quê)

- **Tarefas reais (issues já resolvidas com o commit escondido), qualidade (rubrica + amostra humana) e calibração de juiz:** exigem repositórios reais, modelo, rubrica e limiar, decisões do autor. Nenhum conjunto de tarefas foi inventado.
- **Ablação (contrato de sprint, Avaliador, reset de contexto, multiagente na spec):** não feita. Com executor falso ela só mediria o harness e seria enganosa; com modelo real depende da camada acima. Se vier, deve desligar o componente real por injeção na composição, sem flag de produção que desligue guardrail.
- **Integração como motor do Construtor e do modo noturno:** outro repositório; pendência.
- **"PR recusado em produção vira tarefa de eval"** e leitura semanal de transcrições: processo humano, sem automação.
- O eval do RAG (M2) segue com embeddings falsos e corpus inventado, e diz isso.

## Consequências

- A regressão que bloqueia o merge prova que as proteções corrigidas continuam valendo; não prova que o agente seja bom.
- Mutação por monkeypatch reintroduz o defeito de forma aproximada (não é o diff original); ainda assim cada caso falha quando a proteção sai.
