# 0013. Contextual Retrieval (prefixo de contexto no embedding e no BM25) + reranking, com prompt caching (F-13)

- **Status:** Proposto
- **Data:** 2026-11-21
- **Id no design doc:** F-13 (seção 13; detalhe nas seções 3A e 6.2)

## Contexto

Trechos isolados (uma função, uma seção) perdem o contexto do documento e são recuperados mal. Gerar contexto por trecho com modelo pode ser caro.

## Decisão

Cada trecho recebe um prefixo de contexto gerado por um modelo barato a partir do documento inteiro ("este trecho é a função X do módulo Y, chamada por Z, que valida W"). O documento vai em prompt cacheado, de modo que gerar o prefixo de todos os trechos de um arquivo custa quase o mesmo que um. O texto com prefixo vai para o embedding e para o índice BM25. A busca é híbrida com reranking (ADR 0005).

## Alternativas consideradas

- Prefixo só no embedding ou só no BM25: descartado ("não só para um deles", seção 6.2).

## Consequências

- Melhor recall@20 e menos recuperações falhas (métrica da seção 3A).
- Custo de indexação por chamada de modelo, mitigado por prompt caching.
- Reindexação incremental precisa regenerar prefixos dos trechos afetados.
