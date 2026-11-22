# 0031. Limite de ciclos Test/Build configurável, padrão 3

- **Status:** Proposto
- **Data:** 2026-11-21
- **Id no design doc:** não numerado (seção 5.1 diz "até N ciclos"; M1-03 deixa N para decisão do autor)

## Contexto

Quando a verificação falha, a Entrega volta de Test para Build. Sem limite, um agente que não converge queima orçamento indefinidamente. O design doc não fixa N.

## Decisão

N é um parâmetro da Entrega (`ciclos_maximos`), lido da variável `FORJA_MAX_CICLOS_BUILD_TEST` com padrão 3. Só falhas em Test contam. Com N = 3, as três primeiras falhas voltam ao Build e a quarta é recusada com `CiclosEsgotados`: o estado fica em Test e o workflow escala para um humano. Voltas de Review para Build (achados bloqueantes) não contam, porque têm outro motivo e outro portão.

## Alternativas consideradas

- Constante fixa no código: impede ajustar por repositório ou por política (M5).
- Contar também Review -> Build: mistura dois sinais; o orçamento por intenção (`per_intent_usd`) já limita o total.
- Sem limite e só orçamento: o erro vem tarde e sem causa clara.

## Consequências

- Valor inválido (menor que 1 ou não inteiro) falha na inicialização, não no meio de uma entrega.
- A política de risco do M5 pode passar N por repositório sem mudar o domínio.
- O que acontece depois de `CiclosEsgotados` (comentar na issue, pausar) é decisão do workflow, não do agregado.
