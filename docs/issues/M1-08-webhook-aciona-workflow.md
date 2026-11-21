# M1-08 · Do webhook ao workflow: label inicia, comentário vira sinal

- **core:** false
- **curso:** un-4.7
- **subagente:** implementador + testador
- **depende de:** M1-04, M1-05, M1-07
- **estimativa:** meio dia

## Objetivo

Ligar o gateway ao Temporal por um caso de uso: label `forja:intent` inicia o `DeliveryWorkflow` do Intent; `/forja stop` e eventos repetidos viram sinais; botão de pânico cancela os workflows (seção 7).

## Critérios de aceite

```gherkin
Funcionalidade: Ativação por GitHub

  Cenário: Label inicia o workflow
    Dado um webhook válido de issue com o label "forja:intent"
    Quando o caso de uso roda
    Então um DeliveryWorkflow é iniciado com o id determinístico do Intent

  Cenário: Evento repetido
    Dado o mesmo label aplicado de novo
    Quando o caso de uso roda
    Então nenhuma execução nova é criada

  Cenário: Comando de parar
    Dado um workflow em andamento
    Quando chega "/forja stop" de quem tem permissão de escrita
    Então o workflow recebe o sinal "parar"

  Cenário: Botão de pânico
    Dado vários workflows em andamento
    Quando o botão de pânico é acionado
    Então todos são cancelados e seus sandboxes são destruídos
```

## Arquivos prováveis

- `forja/application/casos_de_uso/ativar_entrega.py`
- `forja/interfaces/http/webhooks.py`, `forja/interfaces/http/panico.py`
- `tests/application/test_ativar_entrega.py`

## Notas

- O botão de pânico é um endpoint protegido; o mecanismo de autenticação do dono (um dono, na v1) precisa de decisão do autor.
- Destruir sandboxes depende do M1-09; até lá a porta de sandbox é um fake.
