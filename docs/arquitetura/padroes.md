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

## SDLC até o PR (M3)

| Padrão ou princípio | Onde | Por quê |
| --- | --- | --- |
| Value Object validado | `domain/artefatos.py` (`IntentMd`, `Spec`, `Plano`, `caminho_relativo_seguro`) | Dado de modelo só vira artefato depois de passar nas invariantes do domínio |
| Parse, don't validate (anti-corruption para saída de LLM) | `agents/esquemas.py`, `agents/estruturado.py` | O resto do sistema nunca vê texto livre de modelo |
| Ports and Adapters | `portas/sdlc.py` (Interprete, Especificador, Planejador, PesquisaDeConhecimento, ListadorDeArquivos) | Trocar o SDK, o RAG ou a origem dos arquivos não toca o workflow |
| Orquestrador-trabalhadores | `EspecificadorMultiagente` | Pesquisadores em paralelo por tipo de fonte, líder escreve a spec (ADR 0017) |
| Strategy (despacho por etapa) | `ExecutorSdlc` | Cada etapa tem um agente; o workflow só conhece o nome da etapa |
| Idempotência por chave e por conteúdo | `PublicadorGitHub` | Retentativa do Temporal não duplica commit, comentário nem PR |
| Dry-run por padrão | `PublicadorGitHub` | Nada é escrito sem `FORJA_PUBLICAR=true` |
| Máquina de portões por sinal | `DeliveryWorkflow` | Decisão humana durável; sinal fora do portão é descartado |
| Defesa em profundidade na saída | `neutralizar_texto` no publicador | Mesmo que o modelo obedeça a injeção, o texto publicado não abre canal |
