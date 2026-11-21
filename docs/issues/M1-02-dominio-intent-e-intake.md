# M1-02 · Domínio: Intent, Origem e eventos do contexto Intake

- **core:** false
- **curso:** fc4-ddd-events
- **subagente:** implementador + testador
- **depende de:** M1-01
- **estimativa:** meio dia

## Objetivo

Modelar em Python puro o agregado `Intent` (problema, origem, critérios de sucesso, link da issue), o objeto de valor `Origem` e os eventos `IntentRecebida` e `IntentConfirmada` (seção 4.1), sem nenhuma dependência de infraestrutura.

## Critérios de aceite

```gherkin
Funcionalidade: Intent e Intake

  Cenário: Intent recebida
    Dado uma origem "issue do GitHub" com título e corpo
    Quando eu crio o Intent
    Então ele tem um id determinístico derivado da origem
    E emite IntentRecebida

  Cenário: Mesmo evento, mesmo id
    Dado duas origens idênticas
    Quando eu crio dois Intents
    Então os ids são iguais

  Cenário: Confirmação
    Dado um Intent recebido
    Quando quem pediu confirma o resumo
    Então o Intent emite IntentConfirmada
    E confirmar de novo não emite evento

  Cenário: Origem inválida
    Dado uma origem sem identificador
    Quando eu crio o Intent
    Então a criação falha com erro de domínio
```

## Arquivos prováveis

- `forja/domain/intent.py`, `forja/domain/eventos.py`
- `tests/domain/test_intent.py`

## Notas

- O id determinístico é a base de "um workflow por intenção" (seção 7); a fórmula exata (repositório + número da issue, por exemplo) precisa de decisão do autor.
