# ADRs: agent-harness (Forja)

Decisões iniciais do [design doc](../design-doc.md) (seção 13), no formato de `docs/adr/0000-template.md`. Todas com status **Proposto** até o autor aceitar. A numeração local (`NNNN`) segue a ordem dos ids do design doc (`F-NN`).

| ADR | Id | Decisão | Marco em que pesa |
| --- | --- | --- | --- |
| [0001](0001-sdlc-maquina-de-estados-com-artefatos.md) | F-01 | AI-native SDLC como máquina de estados com artefatos versionados no repositório-alvo | M1 (domínio), M3 |
| [0002](0002-harness-inicializador-executor.md) | F-02 | Harness inicializador + executor; continuidade em artefatos, uma funcionalidade por sessão | M4 |
| [0003](0003-claude-agent-sdk-e-anthropic-sdk.md) | F-03 | Claude Agent SDK para agentes; SDK anthropic direto para etapas simples | M1 (agente eco) |
| [0004](0004-temporal-orquestracao-duravel.md) | F-04 | Temporal para orquestração durável e sinais de aprovação | M1 |
| [0005](0005-postgres-pgvector-bm25-rrf.md) | F-05 | Postgres + pgvector + BM25 com RRF e reranking | M1 (Postgres), M2 (RAG) |
| [0006](0006-governanca-por-raio-de-impacto.md) | F-06 | Governança por raio de impacto, por hooks e política como código | M4, M5 |
| [0007](0007-github-app-agente-nao-publica.md) | F-07 | GitHub App com permissões mínimas; agente nunca publica, só o workflow | M1 |
| [0008](0008-sandbox-efemero-egress-allowlist.md) | F-08 | Sandbox efêmero por sessão com egress em allowlist; segredos fora do contexto | M1 |
| [0009](0009-evals-continuos-regressao-bloqueia.md) | F-09 | Evals contínuos; regressão bloqueia merge | M2 em diante, M8 |
| [0010](0010-acl-github-sdk-observabilidade.md) | F-10 | ACL para GitHub, Agent SDK e backends de observabilidade | M1 |
| [0011](0011-planner-executor-avaliador-contrato.md) | F-11 | Planner + Executor + Avaliador independente; contrato de sprint | M4 |
| [0012](0012-estrategia-de-contexto-e-memoria.md) | F-12 | Estratégia de contexto por modelo, context editing e memória por repositório | M4 |
| [0013](0013-contextual-retrieval.md) | F-13 | Contextual Retrieval + reranking, com prompt caching | M2 |
| [0014](0014-agent-skills-versionadas.md) | F-14 | Procedimentos como Agent Skills versionadas | M5 |
| [0015](0015-tool-search-e-code-execution-mcp.md) | F-15 | Tool search, programmatic tool calling e code execution com MCP | M7 |
| [0016](0016-sandbox-isolamento-arquivos-e-rede.md) | F-16 | Sandbox com isolamento de arquivos e rede; autonomia total dentro, nada fora | M1 |
| [0017](0017-multiagente-so-em-spec-e-diagnostico.md) | F-17 | Multiagente orquestrador-trabalhadores só em spec e diagnóstico | M3, M6 |
| [0018](0018-evals-no-modelo-anthropic.md) | F-18 | Evals no modelo da Anthropic (capacidade/regressão, pass@k/pass^k, ablação) | M8 |

F-08 e F-16 se sobrepõem (os dois tratam do sandbox); foram mantidos separados porque o design doc os lista separados. O autor pode fundi-los ao aceitar.

Onde o design doc não registra alternativas, o ADR diz isso explicitamente em vez de inventar; o autor completa antes de aceitar.
