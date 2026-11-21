# M1-04 · Gateway FastAPI: webhooks do GitHub com HMAC e deduplicação

- **core:** false
- **curso:** fc4-sec-owasp-vault
- **subagente:** implementador + testador
- **depende de:** M1-01, ADR 0007
- **estimativa:** 1 dia

## Objetivo

Expor `POST /webhooks/github` em FastAPI que verifica a assinatura `X-Hub-Signature-256`, deduplica por `X-GitHub-Delivery` no Redis e ignora, registrando, eventos de quem não tem permissão de escrita (seção 7).

## Critérios de aceite

```gherkin
Funcionalidade: Gateway de webhooks

  Cenário: Assinatura válida
    Dado um payload assinado com o segredo correto
    Quando ele chega ao gateway
    Então a resposta é 202 e o evento segue adiante

  Cenário: Assinatura inválida
    Dado um payload com assinatura errada ou ausente
    Quando ele chega
    Então a resposta é 401 e nada é processado
    E a comparação usa tempo constante

  Cenário: Entrega repetida
    Dado uma entrega com X-GitHub-Delivery já visto
    Quando ela chega de novo
    Então a resposta é 202 e o evento não segue adiante

  Cenário: Autor sem permissão de escrita
    Dado um comentário de usuário sem permissão de escrita no repositório
    Quando o evento chega
    Então ele é ignorado e registrado

  Cenário: Corpo grande
    Dado um corpo acima do limite configurado
    Quando ele chega
    Então a resposta é 413
```

## Arquivos prováveis

- `forja/interfaces/http/webhooks.py`, `forja/interfaces/http/app.py`
- `forja/infrastructure/github/assinatura.py`
- `tests/interfaces/test_webhooks.py`

## Notas

- Segredo do webhook lido do ambiente; nunca em log.
- Texto de issues e comentários é dado, nunca instrução (seção 9.4); aqui só se verifica e se encaminha.
