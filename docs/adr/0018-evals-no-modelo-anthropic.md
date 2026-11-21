# 0018. Evals no modelo da Anthropic: capacidade e regressão, pass@k e pass^k, ambiente limpo, ablação a cada troca de modelo (F-18)

- **Status:** Proposto
- **Data:** 2026-11-21
- **Id no design doc:** F-18 (seção 13; detalhe na seção 11)

## Contexto

Avaliar agentes é diferente de avaliar uma chamada de modelo: há várias tentativas, transcrições longas e efeitos no ambiente. Graders que conferem o que o agente diz, e não o resultado, podem ser burlados.

## Decisão

Os evals seguem o vocabulário tarefa, tentativa, transcrição e resultado; o grader confere o estado final do ambiente, nunca o que o agente diz. Há evals de capacidade (começam baixos) e de regressão (perto de 100%); capacidade saturada gradua para regressão. pass@k onde uma boa solução basta; pass^k onde é preciso consistência (hooks de segurança, máquina de estados). Começo com 20 a 50 tarefas de falhas reais e issues resolvidas, balanceadas entre agir e recusar. Ambiente limpo por tentativa. Juízes de modelo calibrados contra avaliação humana, um por dimensão, com resposta "não sei". Leitura semanal de transcrições. A cada troca de modelo, ablação desligando um componente por vez (contrato de sprint, Avaliador, reset de contexto, multiagente na spec), mantendo só o que muda o resultado.

## Alternativas consideradas

- O design doc não registra alternativas para esta decisão. A preencher pelo autor antes de aceitar.

## Consequências

- Componentes do harness tratados como hipóteses que podem ser removidas.
- Custo de rodar k tentativas por tarefa e de manter ambientes limpos.
- Leitura de transcrições é trabalho humano recorrente.
