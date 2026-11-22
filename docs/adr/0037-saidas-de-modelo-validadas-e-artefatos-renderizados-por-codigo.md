# 0037. Saídas de modelo validadas por schema e artefatos renderizados por código

- **Status:** Proposto
- **Data:** 2026-11-22
- **Id no design doc:** seções 5.2, 5.4 (encadeamento com validação de schema) e 9.4; M3

## Contexto

Intérprete, Spec e Planner escrevem artefatos que o resto do pipeline lê e que vão para o repositório-alvo. Entrada (issue, trechos do RAG, lista de arquivos) é conteúdo não confiável; saída de modelo também não é confiável.

## Decisão

- O modelo devolve só JSON. `AgenteEstruturado` extrai o objeto, valida contra um schema pydantic estrito (campos extras recusados, tamanhos com teto) e converte para um objeto de valor do domínio (`IntentMd`, `Spec`, `Plano`) dentro da mesma validação. Falhou: uma reparação com o erro; falhou de novo: `SaidaInvalida`, erro não retentável que derruba a entrega sem publicar nada.
- O Markdown é renderizado por código: item de lista em uma linha, sem abrir título nem bloco de código. O caminho do arquivo é montado por código (`.forja/<intent-id>/<nome>`, nome de um enum, id validado como 16 hex). Caminhos que o Planner propõe passam por `caminho_relativo_seguro` (relativo, sem `..`, sem `.git`, sem controle).
- Citação obrigatória (seção 6.3): a Spec só pode citar ids de fontes que o RAG de fato devolveu; id inventado recusa a saída. Pesquisadores que citam id inexistente têm a citação descartada.
- Texto externo entra no prompt como dado: `<` e `>` são trocados por aspas angulares tipográficas, então nada fecha a tag que o delimita.
- Nenhum desses agentes tem ferramenta; o repositório (lista de caminhos via `git ls-files`) e o RAG chegam por código (ADR 0036).

## Alternativas consideradas

- Saída estruturada nativa do SDK (`output_format`): reduz tentativas, mas não substitui a validação de domínio; fica como otimização.
- Deixar o agente escrever o arquivo com ferramenta de escrita: abre caminho arbitrário e dá ao texto injetado um canal de persistência.

## Consequências

- Um modelo que viola o schema duas vezes custa duas sessões e encerra a entrega com erro visível (métrica `forja_entregas_erro_total`).
- O custo por etapa é registrado no span `agente.sessao` de cada tentativa.
