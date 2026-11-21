# M1-06 · GitHub App: tokens de instalação e porta de escrita

- **core:** false
- **curso:** fc4-sec-owasp-vault
- **subagente:** implementador + testador
- **depende de:** M1-05, ADR 0007
- **estimativa:** 1 dia

## Objetivo

Autenticar como GitHub App (JWT assinado e tokens de instalação de curta duração) e expor uma porta `GitHubPort` com as escritas mínimas do M1 (comentar em issue, criar branch `forja/<intent-id>-<slug>`), nunca escrevendo na branch padrão (seção 8).

## Critérios de aceite

```gherkin
Funcionalidade: GitHub App

  Cenário: Token de instalação
    Dado a chave privada do App e o id da instalação
    Quando o cliente pede um token
    Então recebe um token de curta duração e o reaproveita até perto de expirar

  Cenário: Comentário na issue
    Dado um Intent com issue de origem
    Quando a porta comenta
    Então a chamada vai à API do GitHub com o token de instalação (mock nos testes)

  Cenário: Branch protegida
    Dado a branch padrão do repositório
    Quando algo tenta criar ou escrever nela
    Então a porta recusa antes de chamar a API

  Cenário: Nome de branch
    Dado o intent-id "abc" e o slug "corrige-login"
    Quando a porta cria a branch
    Então o nome é "forja/abc-corrige-login"

  Cenário: Segredos
    Dado qualquer erro de autenticação
    Quando ele é registrado
    Então chave privada e token não aparecem no log
```

## Arquivos prováveis

- `forja/application/portas/github.py`
- `forja/infrastructure/github/app_auth.py`, `forja/infrastructure/github/cliente.py`
- `tests/infrastructure/github/test_app_auth.py`

## Notas

- Nenhum teste escreve no GitHub de verdade: HTTP é mockado.
- O autor precisa registrar o GitHub App com permissões mínimas (contents, pull requests, issues, checks, metadata) e guardar a chave fora do Git.
