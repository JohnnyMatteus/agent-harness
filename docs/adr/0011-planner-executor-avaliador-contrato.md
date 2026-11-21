# 0011. Planner + Executor + Avaliador independente; contrato de sprint com critérios testáveis e limiares (F-11)

- **Status:** Proposto
- **Data:** 2026-11-21
- **Id no design doc:** F-11 (seção 13; detalhe nas seções 3A e 5.3.1)

## Contexto

O gerador avaliando o próprio trabalho tende a declarar pronto cedo. Há divergência entre "pronto" declarado e "pronto" verificado.

## Decisão

O Build tem três papéis: o Planner expande a intenção em spec de produto, o Executor gera e um Avaliador independente testa o sistema rodando como usuário (Playwright para UI, chamadas reais para API, consultas ao banco). Antes de cada bloco de funcionalidades, Executor e Avaliador fecham um contrato (`sprint-contract.json`, commitado) com o que será entregue e como será verificado. O Avaliador pontua por critério (funcionalidade, profundidade, qualidade de código, aderência a ADRs), com limiares rígidos e exemplos few-shot; abaixo do limiar em qualquer critério, o bloco falha com feedback. Só o Avaliador (via grader de código) muda `passes` para `true`. Para issues `hard`, duas implementações concorrentes em worktrees e o Avaliador escolhe.

## Alternativas consideradas

- Tornar o gerador crítico do próprio trabalho: descartado, porque avaliar fora do gerador é mais fácil de calibrar (seção 3A).

## Consequências

- Defeitos pegos antes do PR; ciclos até verde medidos.
- Mais sessões e tokens por bloco.
- Rubrica, limiares e exemplos de calibração do Avaliador são núcleo do autor (modo par, seção 14).
- A suíte de ablação verifica a cada troca de modelo se contrato e Avaliador continuam necessários.
