# 0005. Postgres + pgvector + BM25 com RRF e reranking; contexto por trecho na indexação (F-05)

- **Status:** Proposto
- **Data:** 2026-11-21
- **Id no design doc:** F-05 (seção 13; detalhe nas seções 4.3, 6.2 e 6.3)

## Contexto

O RAG de engenharia indexa código, ADRs, design docs, issues, PRs, artefatos SDLC, incidentes e o portfólio (seção 6.1). Busca só vetorial erra nomes exatos de símbolos; busca só textual erra paráfrases. O harness também precisa guardar estado.

## Decisão

Um único PostgreSQL 16 guarda estado, vetores (pgvector, HNSW) e índice textual (BM25 via `tsvector`). A recuperação é híbrida: BM25 + vetorial, fusão por Reciprocal Rank Fusion, depois reranking (cross-encoder local ou API), com filtros por metadado aplicados antes do ranqueamento. Cada trecho é indexado com prefixo de contexto (detalhe no ADR 0013).

## Alternativas consideradas

- O design doc não registra alternativas (ex.: banco vetorial dedicado). A preencher pelo autor antes de aceitar.

## Consequências

- Um banco para operar e fazer backup.
- Avaliação no CI (recall@k, MRR, fidelidade, latência p95) quando mudam chunking, embeddings ou reranking (seção 6.5).
- A recuperação híbrida e sua avaliação são núcleo do autor (modo par, seção 14).
- A escolha entre cross-encoder local e API fica em aberto.
