# CLAUDE.md: Forja (agent-harness)

## Visão

Forja é um harness de engenharia autônoma sobre repositórios do GitHub: recebe uma intenção (issue com label `forja:intent`), conduz pelo SDLC (Plan, Design, Build, Test, Review, Deploy, Maintain) com agentes em sandbox, portões humanos por raio de impacto e rastro em git. Fonte de verdade: `docs/design-doc.md`, `docs/adr/` e `docs/issues/`.

## Regras

- Python 3.12, `uv`, `ruff`, `pyright` strict, `pytest`, `hypothesis`. Código em inglês onde for técnico; domínio e docs em português.
- Dependência só aponta para dentro: `domain` não importa nada de fora (só stdlib); `application` importa só `domain`; `infrastructure` e `interfaces` importam as camadas internas. `tests/architecture/` falha se isso quebrar.
- O domínio nunca fala em tipos do GitHub ou do Agent SDK: a ACL fica em `infrastructure/`.
- O agente nunca publica; só o workflow escreve no GitHub (ADR 0007).
- Sem segredos no repositório; `.env` ignorado, `.env.example` versionado. Domínio fictício nos exemplos.
- Máquina de estados é núcleo do autor: mudanças em `forja/domain/{estados,entrega}.py` exigem atualizar `docs/roteiros/maquina-de-estados-sdlc.md` e os testes de propriedade.
- Comentários só com o porquê.

## Comandos

```bash
make install        # uv sync
make check          # lint + pyright + testes (o que o CI roda)
make test           # unitários, sem Docker
make test-integration  # precisa de Docker (testcontainers)
make up             # Postgres+pgvector, Redis, Temporal (perfil core)
make up-all         # + Phoenix (observability)
make down / clean
```

## Estrutura

```text
forja/domain/          Intent, Entrega (máquina de estados), eventos, erros
forja/application/     casos de uso, comandos, portas (Protocols em portas/)
forja/infrastructure/  agents, github, knowledge, sandbox, temporal, telemetry
forja/interfaces/      http (FastAPI), cli, mcp
contracts/             contratos entre partes (schemas, eventos)
docs/                  design doc, ADRs, issues, roteiros
```

## Fluxo de trabalho

1. Leia a issue em `docs/issues/` e os ADRs citados; critérios Gherkin são o que precisa passar.
2. Teste primeiro para regras de domínio; propriedades com hypothesis para invariantes.
3. `make check` antes de commitar. Commits em Conventional Commits, mensagem via arquivo (`git commit -F`).
4. Branches `feat/*`; o workflow `CI` precisa ficar verde, e a automação `Promote` leva para a `main`.
5. Decisão nova que o design doc não cobre vira ADR em `docs/adr/` (próximo número livre).
