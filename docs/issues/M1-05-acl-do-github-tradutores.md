# M1-05 · ACL do GitHub: tradutores de payload para o domínio

- **core:** false
- **curso:** fc4-arch-hexagonal
- **subagente:** implementador + testador
- **depende de:** M1-02, M1-04, ADR 0010
- **estimativa:** 1 dia

## Objetivo

Criar a Anti-Corruption Layer do GitHub: tradutores que convertem payloads de webhook (issue com label `forja:intent`, comentário `/forja ...`, PR) em comandos e `Intent` do domínio, para que o domínio nunca veja `IssueCommentEvent` (seção 4.4).

## Critérios de aceite

```gherkin
Funcionalidade: ACL do GitHub

  Cenário: Label de intenção
    Dado o payload de uma issue recebendo o label "forja:intent"
    Quando o tradutor roda
    Então devolve um comando CriarIntent com a origem preenchida

  Cenário: Comando em comentário
    Dado um comentário "/forja stop" em uma issue com Intent
    Quando o tradutor roda
    Então devolve o comando Parar para o Intent correspondente

  Cenário: Comando desconhecido
    Dado um comentário "/forja dance"
    Quando o tradutor roda
    Então devolve um resultado "ignorado" com o motivo, sem lançar exceção

  Cenário: Payload de versão nova
    Dado um payload com campos desconhecidos
    Quando o tradutor roda
    Então os campos extras são ignorados e o essencial é traduzido

  Cenário: Isolamento
    Dado o código de "forja/domain" e "forja/application"
    Quando o teste de arquitetura roda
    Então nenhum tipo do GitHub aparece fora de "forja/infrastructure/github"
```

## Arquivos prováveis

- `forja/infrastructure/github/tradutores.py`
- `forja/application/comandos.py`
- `tests/fixtures/github/*.json` (payloads anonimizados)
- `tests/infrastructure/github/test_tradutores.py`

## Notas

- Fixtures de payload são de repositórios fictícios, sem nome de cliente ou empregador.
- Conjunto de comandos do M1: `CriarIntent` e `Parar`; `/forja spec`, `/forja build` e `/forja review` entram nos marcos seguintes.
