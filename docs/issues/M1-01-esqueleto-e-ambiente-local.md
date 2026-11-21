# M1-01 · Esqueleto do repositório e ambiente local

- **core:** false
- **curso:** fc4-arch-hexagonal
- **subagente:** implementador + devops
- **depende de:** ADR 0003
- **estimativa:** 1 dia

## Objetivo

Criar o repositório da Forja com a estrutura hexagonal da seção 4.4, o ferramental de qualidade (uv, ruff, pyright, pytest) e um `docker compose` único com Postgres 16 (pgvector), Temporal e Redis, mais o CI do GitHub Actions.

## Critérios de aceite

```gherkin
Funcionalidade: Esqueleto e ambiente local

  Cenário: Ambiente sobe com um comando
    Dado um clone limpo do repositório
    Quando eu rodo "docker compose up -d" e espero os healthchecks
    Então Postgres, Temporal e Redis ficam saudáveis

  Cenário: Qualidade verde
    Dado o esqueleto sem funcionalidades
    Quando eu rodo "uv run ruff check", "uv run pyright" e "uv run pytest"
    Então os três passam

  Cenário: Domínio sem dependência de infraestrutura
    Dado o pacote "forja/domain"
    Quando o teste de arquitetura importa o pacote
    Então ele não importa FastAPI, Temporal, SDKs nem "forja.infrastructure"

  Cenário: CI
    Dado um PR
    Quando o workflow de CI roda
    Então lint, tipos e testes unitários rodam e passam
```

## Arquivos prováveis

- `pyproject.toml`, `uv.lock`, `ruff.toml`
- `forja/{domain,application,infrastructure,interfaces}/__init__.py`
- `docker-compose.yml`, `.github/workflows/ci.yml`
- `tests/architecture/test_camadas.py`

## Notas

- Sem `.env` no repositório; só `.env.example` com nomes de variáveis.
- Helm fica para o fim do projeto (seção 15, "Complexidade operacional").
