# Padrões e princípios aplicados

Registro dos padrões de projeto e dos princípios SOLID usados, por contexto. Cada bloco diz o padrão, onde está e por quê.

## Knowledge (M2)

| Padrão ou princípio | Onde | Por quê |
| --- | --- | --- |
| Ports and Adapters | `application/portas/knowledge.py` (porta) e `infrastructure/knowledge/` (adaptadores) | O caso de uso não sabe se o índice é Postgres ou memória, nem se o embedding é falso ou de modelo |
| Dependency Inversion | `IndexarRepositorio` recebe fonte, chunker, embedder, gerador e índice por construtor | Trocar uma peça não mexe nas outras |
| Open/Closed | Nova linguagem entra por gramática no chunker; novo gerador de contexto, por outra implementação da porta | Estender sem alterar o caso de uso |
| Value Object | `Escopo`, `Trecho` (imutáveis, validados na criação) | O isolamento por organização e repositório não pode ser esquecido nem alterado |
| Função pura no domínio | `fundir_rrf` | Regra de fusão testável sem infraestrutura |
| Idempotência por versão de conteúdo | `IndexarRepositorio` | Reexecutar (webhook repetido, retry do Temporal) não duplica nem reescreve |
| Escopo obrigatório na assinatura (isolamento por construção) | `IndiceDeTrechos`, `RecuperarConhecimento` | Esquecer o filtro vira erro de tipo, não vazamento |
| Defesa em profundidade | `RecuperarConhecimento` descarta trecho de outro escopo | O índice pode ter defeito; o caso de uso não confia |
| Capability token (escopo assinado) | `token_sessao.py`, `interfaces/mcp/knowledge.py` | O modelo não escolhe o escopo; a ferramenta nem tem o parâmetro |
| Closure sobre o escopo da sessão | `criar_servidor` | O escopo é capturado uma vez, na construção, e não circula como dado |
| Golden file / baseline versionada | `evals/rag/baseline.json`, `avaliacao.py` | Regressão de métrica falha o teste; mudar corpus exige renovar a baseline de propósito |
| Test double determinístico | `EmbedderFalso` | Reprodutível e sem rede; declara no próprio resultado o que não prova |
| Composition root fino | `interfaces/mcp/composicao.py`, `interfaces/cli/indexar.py` | A ligação com o ambiente fica na borda; configuração ruim falha, não improvisa |
| Fail fast em configuração | `configuracao.py` | Embedder real inexistente não é simulado |
