# 0052. Servidor MCP knowledge: escopo vem do token da sessão, nunca de argumento do modelo

- **Status:** Proposto
- **Data:** 2026-11-22
- **Id no design doc:** seção 6.4 (M2 Knowledge)

## Contexto

O servidor MCP `knowledge` é chamado pelo agente. Qualquer parâmetro que ele receba pode ter sido influenciado por conteúdo hostil (issue, arquivo indexado). Se organização e repositório fossem argumentos, um prompt injection bastaria para ler outro repositório.

## Decisão

- O escopo é fixado na construção do servidor (`criar_servidor(recuperador, indice, escopo)`), a partir de um token de sessão JWT HS256 assinado pelo workflow, com `sub` (sessão), `aud`, `org`, `repo` e `exp` obrigatórios, algoritmo fixado (rejeita `none`), segredo de pelo menos 32 bytes e validade curta (padrão 2 h). O servidor só verifica; quem emite é o workflow ao abrir a sessão.
- Nenhuma ferramenta tem parâmetro de organização ou repositório. O design doc lista `repo?` em `search_code` e `repo` em `get_symbol`; esses parâmetros foram removidos de propósito. Há teste sobre o schema das ferramentas.
- Ferramentas entregues: `search_code(query, lang?, k, offset)`, `search_docs(query, tipo?, k, offset)` e `get_symbol(path, symbol)`. Parâmetros validados com tetos (consulta 500 caracteres, k até 20, deslocamento até 200).
- Respostas enxutas: trecho resumido a 600 caracteres, símbolo completo até 20 000, `ha_mais` e `proximo_deslocamento`, commit em cada item (citação). Todo retorno leva o aviso de que o conteúdo é dado não confiável; o conteúdo vai sempre dentro de campos nomeados, nunca como texto solto.
- Transporte stdio, um processo por sessão. Servir várias sessões num processo HTTP exigiria o token em cada requisição; fica para quando houver necessidade.

## Alternativas consideradas

- Escopo como argumento validado contra uma lista permitida: o modelo ainda escolhe, e a lista vira ponto de erro.
- Token sem expiração ou segredo compartilhado fraco: rejeitados; o token vive só durante a sessão.

## Consequências

- `similar_incidents` e `related_prs` do design doc não foram feitos: dependem de corpus de incidentes e PRs que ainda não é indexado.
- `get_symbol` não devolve chamadores principais (exige grafo de chamadas).
- O token protege o escopo, não o conteúdo: um repositório hostil ainda pode conter texto que tenta induzir o agente; o aviso e a estrutura reduzem, não eliminam, esse risco.
