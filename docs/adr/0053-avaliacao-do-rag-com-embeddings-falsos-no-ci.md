# 0053. Avaliação do RAG no CI com corpus inventado e embeddings falsos, métricas versionadas

- **Status:** Proposto
- **Data:** 2026-11-22
- **Id no design doc:** seção 6.5 (M2 Knowledge); complementa os ADRs 0009 e 0018

## Contexto

O design doc pede 100 perguntas sobre os repositórios do autor, com recall@k, MRR, fidelidade e latência p95, rodando no CI quando mudam chunking, embeddings ou reranking. O CI não tem modelo de embedding nem credencial, e o conjunto real de perguntas é do autor (núcleo, seção 14).

## Decisão

- O eval do CI usa um corpus inventado (`evals/rag/corpus`, um armazém fictício em Python, TypeScript e ADRs em Markdown), 16 perguntas com a resposta de referência (caminho e símbolo) e embeddings falsos determinísticos (hash de termos, 64 dimensões). Roda dentro do `pytest`, sem rede e sem baixar modelo.
- Métricas: recall@1, recall@3, recall@5 e MRR. Ficam em `evals/rag/baseline.json` com `versao_metricas`, o pipeline (`chunker+embedder+contexto`) e o SHA do corpus e das perguntas.
- Regra: mudar corpus ou perguntas exige renovar a baseline de propósito (`python -m forja.infrastructure.knowledge.avaliacao --atualizar`, com o diff revisado). Qualquer métrica abaixo da baseline falha o teste. Melhorar não falha.
- A baseline e o resultado carregam o aviso de que os números validam o encanamento (chunking, fusão, isolamento) e não dizem nada sobre a qualidade de um modelo real. Os valores atuais são o que o pipeline lexical-hash entrega, sem ajuste para parecer bom.

## Alternativas consideradas

- Baixar um modelo pequeno de embedding no CI: custo de rede e disco, resultado dependente de versão; descartado nesta etapa.
- Chamar a API de embeddings no CI: exige segredo e gera custo e flakiness.

## Consequências

- Não cobre fidelidade da resposta (precisa de grader de modelo) nem latência p95 (precisa de Postgres e carga realistas), nem as 100 perguntas do autor. Ficam pendentes.
- Um eval com embedder real, sobre repositórios reais, é uma etapa separada e manual até haver credencial.
- O corpus pequeno satura rápido; a baseline serve para detectar regressão, não para comparar abordagens.
