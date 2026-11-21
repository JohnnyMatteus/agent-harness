# 0009. Evals contínuos com graders de código, modelo e humano; regressão bloqueia merge (F-09)

- **Status:** Proposto
- **Data:** 2026-11-21
- **Id no design doc:** F-09 (seção 13; detalhe na seção 11)

## Contexto

Prompts, skills, ferramentas, modelos e políticas mudam o comportamento do harness sem mudar o código. Sem avaliação contínua, regressões de qualidade e de segurança passam despercebidas.

## Decisão

O harness tem evals em níveis (unidade de agente, tarefa, qualidade, segurança, RAG, custo e eficiência; tabela da seção 11) com graders de código, de modelo (rubrica) e amostra humana. A suíte de regressão roda no CI a cada mudança de prompt, skill, ferramenta, modelo ou política, e regressão bloqueia o merge. PR recusado em produção vira nova tarefa de eval.

## Alternativas consideradas

- Avaliação só como fase final: descartado pelo princípio "evals contínuos, não fase final" (seção 3).

## Consequências

- Mudanças de prompt e de modelo passam a ter teste.
- Custo de rodar evals com modelo real no CI.
- Detalhes de método no ADR 0018.
