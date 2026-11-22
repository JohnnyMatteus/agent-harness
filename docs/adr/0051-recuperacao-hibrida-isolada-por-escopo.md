# 0051. Recuperação híbrida com RRF, isolada por organização e repositório na própria consulta

- **Status:** Proposto
- **Data:** 2026-11-22
- **Id no design doc:** seção 6.3 (M2 Knowledge); complementa os ADRs 0005 e 0013

## Contexto

A recuperação híbrida e sua avaliação são núcleo do autor (design doc, seção 14). Este ADR registra o que o código assume até o autor decidir diferente. Em um índice compartilhado por vários repositórios, um filtro esquecido vaza código de um repositório para o agente de outro.

## Decisão

- `RecuperarConhecimento.buscar` exige um `Escopo` (organização + repositório) e o repassa às duas consultas ao índice (lexical e vetorial). Não existe método de busca sem escopo na porta `IndiceDeTrechos`. O filtro entra na própria consulta, antes do ranqueamento, e não depois dela.
- Defesa em profundidade: o caso de uso descarta qualquer trecho cujo escopo difira do pedido, mesmo que o índice o devolva.
- Fusão por Reciprocal Rank Fusion, `1/(60 + posição)` somado entre as listas, desempate pelo id (função pura `fundir_rrf`). O valor 60 é o padrão da literatura e não foi calibrado.
- Filtros de tipo e linguagem entram na consulta. Paginação por `limite` (máx. 50) e `deslocamento`, com `ha_mais`.
- Reranking: a porta existe e o padrão mantém a ordem da fusão. A escolha entre cross-encoder local e API continua em aberto (ADR 0005); nada foi implementado.

## Alternativas consideradas

- Uma tabela ou schema por repositório: isolamento mais forte, custo operacional alto com muitos repositórios. Row-level security no Postgres pode ser somada depois; não substitui o filtro na consulta.
- Filtrar depois da busca global: rejeitado, vaza por canal lateral (ranking, contagem) e erra o top-k.

## Consequências

- O teste de vazamento roda o mesmo conteúdo em três escopos (outro repositório, outra organização) e exige resultado só do próprio.
- Os pesos da fusão, o tamanho do pool (50 por lista), o reranker e as métricas de aceite são decisões do autor, listadas como pendentes.
