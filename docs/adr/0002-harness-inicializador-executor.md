# 0002. Harness inicializador + executor; continuidade em artefatos, uma funcionalidade por sessão (F-02)

- **Status:** Proposto
- **Data:** 2026-11-21
- **Id no design doc:** F-02 (seção 13; detalhe na seção 5.3)

## Contexto

Em sessões longas, o agente perde contexto, declara vitória cedo e deixa o repositório em estado quebrado (seção 1). A etapa Build precisa avançar por várias sessões sem depender da memória do modelo.

## Decisão

Na primeira sessão, o Inicializador lê `spec.md` e `plan.md` e cria `feature_list.json` (funcionalidades de ponta a ponta com `categoria`, `descricao`, `passos_de_teste` e `passes: false`), `progress.md`, `init.sh` e o commit inicial. Em cada sessão seguinte, o Executor confirma diretório e branch, lê `progress.md` e o git log, escolhe a funcionalidade de maior prioridade ainda falhando, roda `init.sh` e um teste básico de ponta a ponta, implementa uma funcionalidade, testa como usuário, commita e deixa a branch limpa. Por hook: só o campo `passes` muda no `feature_list.json`; editar ou remover testes existentes é bloqueado salvo issue aprovada de refatoração de testes; `passes: true` só depois de o grader de código confirmar.

## Alternativas consideradas

- Lista de funcionalidades em Markdown: descartada porque o modelo tende mais a reescrever ou sobrescrever Markdown do que JSON (seção 5.3).

## Consequências

- Progresso verificável e retomável entre sessões.
- Uma funcionalidade por sessão aumenta o número de sessões e o custo fixo de reabrir contexto.
- Depende dos hooks do ADR 0006 e do grader do ADR 0011.
