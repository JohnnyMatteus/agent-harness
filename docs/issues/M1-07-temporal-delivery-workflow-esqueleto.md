# M1-07 · Temporal: DeliveryWorkflow esqueleto com id determinístico e sinais

- **core:** false
- **curso:** un-4.6
- **subagente:** implementador + testador
- **depende de:** M1-01, M1-03, ADR 0004
- **estimativa:** 1 dia

## Objetivo

Criar o `DeliveryWorkflow` do Temporal (Python SDK) com id determinístico por intenção, que percorre a máquina de estados do M1-03 recebendo sinais (`confirmar`, `parar`) e executando uma activity por etapa (seção 7.1).

## Critérios de aceite

```gherkin
Funcionalidade: DeliveryWorkflow

  Cenário: Um workflow por intenção
    Dado um Intent com id "abc"
    Quando o workflow é iniciado duas vezes
    Então existe uma única execução com o workflow id "abc"
    E a segunda tentativa vira sinal, não execução nova

  Cenário: Sinal de confirmação
    Dado um workflow aguardando confirmação do Intent
    Quando chega o sinal "confirmar"
    Então a Entrega avança de Plan para Design

  Cenário: Cancelamento
    Dado um workflow em andamento
    Quando chega o sinal "parar"
    Então o workflow termina como cancelado
    E a activity em curso recebe o cancelamento

  Cenário: Sobrevive a reinício
    Dado um workflow aguardando sinal
    Quando o worker é reiniciado
    Então o workflow continua aguardando e aceita o sinal depois

  Cenário: Timer de lembrete
    Dado um workflow aguardando aprovação além do prazo configurado
    Quando o timer dispara
    Então o workflow registra o lembrete (sem enviar nada externo no M1)
```

## Arquivos prováveis

- `forja/infrastructure/temporal/workflows.py`, `forja/infrastructure/temporal/activities.py`, `forja/infrastructure/temporal/worker.py`
- `tests/infrastructure/temporal/test_delivery_workflow.py` (ambiente de teste de tempo do Temporal)

## Notas

- Só o `DeliveryWorkflow` entra no M1; `ReviewWorkflow`, `NightlyWorkflow` e `IncidentWorkflow` ficam para os marcos deles.
- Prazo do timer (o design doc cita 48 h como exemplo) é configuração.
