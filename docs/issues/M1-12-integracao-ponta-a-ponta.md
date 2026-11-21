# M1-12 · Integração ponta a ponta: label na issue até comentário do eco

- **core:** false
- **curso:** fc4-tests-testcontainers
- **subagente:** testador
- **depende de:** M1-06, M1-08, M1-10, M1-11
- **estimativa:** 1 dia

## Objetivo

Provar o M1 em um teste de integração: um webhook assinado de issue com o label `forja:intent` percorre gateway, Temporal e sandbox, o agente eco responde e é o workflow (não o agente) quem comenta na issue, com tudo num trace só.

## Critérios de aceite

```gherkin
Funcionalidade: Fundação ponta a ponta

  Cenário: Caminho feliz
    Dado o ambiente do compose e um GitHub falso
    Quando um webhook assinado de "forja:intent" chega ao gateway
    Então um DeliveryWorkflow é iniciado
    E o agente eco roda num sandbox
    E a resposta é publicada como comentário na issue pelo workflow
    E existe um único trace com todos os passos

  Cenário: O agente não publica
    Dado o sandbox do eco
    Quando ele tenta chamar a API do GitHub
    Então a rede bloqueia a chamada

  Cenário: Entrega repetida
    Dado o mesmo webhook enviado duas vezes
    Quando o fluxo termina
    Então há um único comentário e uma única execução

  Cenário: Parar no meio
    Dado um fluxo em andamento
    Quando chega "/forja stop"
    Então o workflow é cancelado e o sandbox é destruído
```

## Arquivos prováveis

- `tests/integracao/test_fundacao.py`
- `tests/integracao/github_falso.py`
- `.github/workflows/integracao.yml`

## Notas

- O GitHub é um servidor falso local; nada vai ao GitHub de verdade.
- A chamada ao modelo usa o SDK falso do M1-10; um teste manual opcional pode usar o modelo real.
