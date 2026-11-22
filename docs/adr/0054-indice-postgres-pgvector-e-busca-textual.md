# 0054. Índice Postgres: pgvector HNSW com varredura iterativa e busca textual por tsvector

- **Status:** Proposto
- **Data:** 2026-11-22
- **Id no design doc:** seção 6.2 (M2 Knowledge); concretiza o ADR 0005

## Contexto

O ADR 0005 escolhe Postgres, pgvector e BM25 via `tsvector`. Faltavam os detalhes do adaptador e o que ele não entrega.

## Decisão

- Duas tabelas: `knowledge_arquivo` (versão por arquivo, base da incrementalidade) e `knowledge_trecho` (metadados, texto, `busca` normalizada, `tsvector` gerado e `vector(N)` com índice HNSW de cosseno). Chaves primárias começam por `(organizacao, repositorio)`, e todo SELECT, DELETE e UPDATE leva as duas colunas.
- A normalização do texto (camelCase e snake_case em termos) é feita em Python e é a mesma na indexação e na consulta; a consulta vira um `tsquery` só com termos `[a-z0-9]` unidos por OU, então não há sintaxe de `tsquery` vinda do modelo.
- Ranking textual por `ts_rank_cd`. Isso aproxima BM25 (frequência e cobertura de termos), mas não é BM25: não há saturação de frequência nem normalização de comprimento como no BM25. O índice em memória usado no eval implementa BM25 de verdade, então as duas implementações podem ordenar diferente.
- HNSW filtrado por escopo usa `hnsw.iterative_scan = strict_order` na transação da consulta (exige pgvector 0.8 ou superior); sem isso, o filtro aplicado depois do índice pode devolver menos resultados que o pedido.
- A dimensão do vetor é fixada na criação da tabela; trocar de embedder com outra dimensão exige migração (a versão do pipeline já força reindexar, mas não altera a coluna).
- Uma conexão por operação, sem pool.

## Alternativas consideradas

- Extensão de BM25 real (pg_search ou similar): fiel ao nome, mas mais uma extensão para operar; fica como opção do autor.
- Row-level security por escopo: reforço possível; não substitui o filtro explícito.

## Consequências

- Este adaptador só foi exercitado pelo teste de integração (`tests/infrastructure/knowledge/test_postgres_integracao.py`, contêiner `pgvector/pgvector:pg16`); nenhum Postgres real foi consultado no desenvolvimento local.
- O eval do ADR 0053 não passa pelo Postgres, logo não valida o ranking textual do `ts_rank_cd`.
- Não há embedding real: o entrypoint recusa `FORJA_EMBEDDER` diferente de `falso` (ver README).
