# Forja

![CI](https://github.com/JohnnyMatteus/agent-harness/actions/workflows/ci.yml/badge.svg)

Harness autônomo de engenharia com RAG: a infraestrutura em volta do modelo que dá a ele ciclo de trabalho (SDLC), ferramentas, limites, gatilhos e observabilidade, para agentes trabalharem com autonomia segura sobre repositórios no GitHub.

## O problema

Em times com agentes de código, o gargalo deixou de ser escrever código e passou a ser planejar, revisar e entregar. Sem estrutura, o agente perde contexto entre sessões, ninguém sabe por que uma mudança foi feita e não há como limitar o que ele pode fazer sozinho. A Forja transforma uma issue em uma entrega rastreável: cada etapa produz um artefato versionado (`intent.md`, `spec.md`, `plan.md`, `review.md`), humanos decidem onde o risco exige, e a cadeia de commits serve de auditoria.

## Estado atual (M1, M3 e M4)

| Pronto | Em andamento em outras branches |
| --- | --- |
| Esqueleto hexagonal, qualidade (ruff, pyright strict, pytest, hypothesis), CI | |
| Domínio: `Intent` com id determinístico, `Origem`, eventos de Intake | |
| Domínio: máquina de estados da `Entrega` com testes de propriedade | |
| Gateway de webhooks (HMAC, deduplicação), ACL e cliente do GitHub App | |
| Ambiente local: Postgres+pgvector, Redis, Temporal dev server, Phoenix | |
| `DeliveryWorkflow` no Temporal (teste com test server), agente eco e telemetria | |
| Sandbox Docker efêmero (sem root, `--read-only`, rede interna, proxy Squid em allowlist), ADR 0032 | |
| Binário `forja serve` e `forja worker` (ADR 0033): webhook verificado, `DeliveryWorkflow`, agente eco sem ferramenta e com ambiente isolado (ADR 0036), comentário publicado só pelo workflow (dry-run por padrão, ADR 0034), trace único e `/metrics` | |
| Teste de integração ponta a ponta com GitHub falso (`tests/integracao/`); o isolamento do SDK tem teste do comando e do ambiente efetivos | |

| M3, SDLC até o PR: Intérprete, Spec (pesquisadores em paralelo sobre o RAG do M2, citação obrigatória), Planner, artefatos em `.forja/<intent-id>/`, portão de spec por `/forja approve` e `/forja reject`, PR em rascunho (ADRs 0037 e 0038); teste ponta a ponta em `tests/integracao/test_sdlc_ponta_a_ponta.py` | |
| M4, harness de longa duração: Inicializador, blocos com contrato de sprint, Executor com ferramentas no sandbox sob guardrails (PreToolUse e auditoria do diff), grader de código, Avaliador independente com context editing, memória por repositório, verificação final e PR (ADRs 0039 a 0041). Ligado por `FORJA_HARNESS=true` (exige aceite explícito do risco da chave no sandbox, ADR 0040); a fronteira de segurança é o container, não a allowlist de comandos; teste ponta a ponta com git real em `tests/integracao/test_harness_ponta_a_ponta.py` | O modo `docker` do lançador e a imagem `forja-agente` não foram exercitados contra Docker real |

RAG (M2) está na main; política de risco, evals e o harness de longa duração ficam para os marcos seguintes (ver [Próximos passos](#próximos-passos)).

## Arquitetura

Hexagonal: o domínio é Python puro; o mundo externo entra por portas (`Protocol`) e tradutores (ACL).

```mermaid
flowchart LR
  GH["GitHub<br/>webhooks"] --> HTTP["interfaces/http<br/>FastAPI, HMAC, dedup"]
  HTTP --> ACL["infrastructure/github<br/>ACL"]
  ACL --> APP["application<br/>casos de uso e portas"]
  APP --> DOM["domain<br/>Intent, Entrega, eventos"]
  APP --> TEMP["infrastructure/temporal<br/>workflows"]
  TEMP --> AG["infrastructure/agents<br/>Agent SDK"]
  AG --> SBX["infrastructure/sandbox<br/>container efêmero"]
  TEMP --> GHW["GitHub (escrita só<br/>pelo workflow)"]
  AG -.-> TEL["infrastructure/telemetry<br/>OpenTelemetry"]
```

```text
forja/
  domain/            Intent, Entrega (máquina de estados), eventos, erros
  application/       casos de uso, comandos e portas
  infrastructure/    agents, github, knowledge, sandbox, temporal, telemetry
  interfaces/        http, cli, mcp
```

A regra de dependência é verificada por `tests/architecture/`.

### Máquina de estados da entrega

```mermaid
stateDiagram-v2
  [*] --> Plan: IntentRecebida
  Plan --> Design: intent.md confirmado
  Design --> AguardandoSpec: pontos em aberto
  AguardandoSpec --> Build: humano resolve
  Design --> Build: spec fechada
  Build --> Test
  Test --> Build: falha (até N ciclos, padrão 3)
  Test --> Review: verde
  Review --> Build: achados bloqueantes
  Review --> AguardandoHumano: raio alto
  Review --> Deploy: raio baixo
  AguardandoHumano --> Deploy: aprovado
  Deploy --> Maintain
```

Detalhes, alternativas e perguntas de entrevista em [docs/roteiros/maquina-de-estados-sdlc.md](docs/roteiros/maquina-de-estados-sdlc.md).

## Como rodar

Pré-requisitos: Python 3.12, [uv](https://docs.astral.sh/uv/) e Docker.

```bash
cp .env.example .env     # valores de desenvolvimento
make install             # uv sync
make up                  # Postgres+pgvector, Redis e Temporal, com healthchecks
make up-all              # opcional: inclui o Phoenix (traces) em http://localhost:6006
make ps
make down                # make clean também remove os volumes
```

| Serviço | Porta padrão | Perfil |
| --- | --- | --- |
| Postgres 16 + pgvector | 5432 | core |
| Redis | 6379 | core |
| Temporal (UI em 8233) | 7233 | core |
| Phoenix (OTLP em 4317) | 6006 | observability |

Portas e a senha de desenvolvimento (`dev-only-change-me`) são variáveis do `.env`.

## Knowledge (M2)

Indexação incremental por SHA (tree-sitter para Python e TypeScript, cabeçalho para Markdown), recuperação híbrida (busca textual + pgvector, fusão RRF) isolada por organização e repositório na própria consulta, e servidor MCP `knowledge` cujo escopo vem de um token de sessão assinado. Conteúdo indexado é tratado como não confiável: sem symlink, sem segredo, com limite de tamanho, devolvido como dado. ADRs 0050 a 0054.

```bash
export DATABASE_URL=postgresql://forja:dev-only-change-me@localhost:5432/forja
export FORJA_EMBEDDER=falso   # único suportado; não há adaptador de embedding real
uv run python -m forja.interfaces.cli.indexar --raiz . --org acme --repo loja --commit "$(git rev-parse HEAD)"
# o workflow emite FORJA_KNOWLEDGE_TOKEN (forja.infrastructure.knowledge.token_sessao.emitir_token)
# e o agente sobe o servidor por stdio: python -m forja.interfaces.mcp
```

Limites declarados: o adaptador Postgres só foi exercitado pelo teste de integração (contêiner com pgvector), não contra um banco real; a busca textual usa `ts_rank_cd`, que aproxima BM25 mas não é BM25; o eval do CI usa embeddings falsos e corpus inventado (`evals/rag/`) e não diz nada sobre qualidade de modelo real.

## Como testar

```bash
make check               # ruff, pyright strict e testes: o mesmo que o CI roda
make test                # só os unitários, sem Docker
make test-integration    # testes com testcontainers (rodam no CI)
```

O núcleo tem testes por exemplo (cenários Gherkin das issues) e por propriedade com hypothesis: nenhuma sequência de comandos chega a Deploy sem passar por Review, e todo comando recusado deixa o agregado intacto.

## Decisões principais

Todas em [docs/adr/](docs/adr/README.md). As que moldam este repositório:

- [0001](docs/adr/0001-sdlc-maquina-de-estados-com-artefatos.md): SDLC como máquina de estados com artefatos no repositório-alvo.
- [0004](docs/adr/0004-temporal-orquestracao-duravel.md): Temporal para orquestração durável.
- [0007](docs/adr/0007-github-app-agente-nao-publica.md): GitHub App; o agente nunca publica.
- [0010](docs/adr/0010-acl-github-sdk-observabilidade.md): ACL para GitHub, Agent SDK e observabilidade.
- [0030](docs/adr/0030-id-deterministico-da-intent.md): id da Intent é um hash de tipo, repositório e identificador da origem (garante "um workflow por intenção").
- [0031](docs/adr/0031-limite-de-ciclos-build-test-configuravel.md): limite de ciclos Test/Build configurável (`FORJA_MAX_CICLOS_BUILD_TEST`, padrão 3).

## Trade-offs

- **Temporal em vez de fila e cron:** mais um serviço para operar, em troca de espera por humano, timers e retomada sem código próprio. No compose local usa o dev server (SQLite).
- **Phoenix em vez de Langfuse local:** Langfuse exige ClickHouse, Redis e S3 próprios; Phoenix sobe com um container e fala OTLP. O backend fica atrás de um adaptador.
- **Domínio sem frameworks:** mais código de mapeamento nas bordas, mas regras testáveis em milissegundos e sem acoplamento ao GitHub ou ao SDK.
- **Estados como comandos nomeados:** mais métodos que um `avancar(evento)` genérico, porém cada regra fica legível e tipada.

## Próximos passos

- Agentes com ferramenta (M3/M4) rodam o CLI dentro do sandbox (modo `docker` do lançador, ADR 0036): a imagem com o CLI e o modo ainda não foram exercitados contra Docker real.
- Rejeição como aresta da máquina de estados: hoje a rejeição encerra o workflow (ADR 0038); decisão do autor.
- Política de risco e hooks (M5) e evals contínuos (M8).
- Knowledge (M2) pendente: adaptador de embedding real (hoje só o falso, e só por escolha explícita), reranker, prefixo de contexto gerado por modelo (ADR 0013), `similar_incidents` e `related_prs`, indexação disparada por webhook, fidelidade e latência p95 no eval.
- Helm e implantação em cluster.

## Documentação

[Design doc](docs/design-doc.md) · [ADRs](docs/adr/README.md) · [Issues do M1](docs/issues/README.md) · [GitHub App](docs/github-app.md) · [CLAUDE.md](CLAUDE.md)

## Licença

MIT.
