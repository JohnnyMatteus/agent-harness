# 0050. Indexação idempotente e incremental por SHA; conteúdo indexado é não confiável

- **Status:** Proposto
- **Data:** 2026-11-22
- **Id no design doc:** seções 6.1 e 6.2 (M2 Knowledge); complementa o ADR 0005

## Contexto

O design doc pede chunking por tree-sitter e reindexação só dos arquivos alterados. O conteúdo de um repositório é entrada não confiável: pode ter symlink para fora do checkout, segredo commitado, arquivo gigante ou texto escrito para enganar um agente.

## Decisão

- Chunking por estrutura: tree-sitter para Python e TypeScript (função, classe, método, resto do módulo), cabeçalho para Markdown (com a cerca de código respeitada), janelas de linhas com sobreposição pequena para o resto. Trecho acima de 2400 caracteres (aprox. 600 tokens) é partido.
- Incrementalidade: o índice guarda, por arquivo, `sha256(conteúdo)@versão-do-pipeline`. A versão do pipeline junta as versões do chunker, do embedder e do gerador de contexto, então trocar qualquer um reindexa tudo. Arquivo igual não é escrito; arquivo que sumiu é removido; a troca dos trechos de um arquivo é atômica. Rodar duas vezes é no-op.
- Ingestão defensiva (`varredura.py`): não segue symlink (nem de diretório; abre com `O_NOFOLLOW`), aceita só arquivo regular, limita bytes por arquivo, por quantidade e no total, recusa binário e não UTF-8, e recusa o arquivo inteiro (não censura trechos) se o nome ou o conteúdo indicar segredo (chave privada, AWS, GitHub, Anthropic, Slack, Google, atribuição literal de senha/token). Recusas são contadas por motivo; o conteúdo recusado nunca é devolvido nem logado.
- Na saída, o trecho é sempre dado, nunca instrução (ADR 0052).
- O prefixo de contexto padrão é determinístico (tipo, linguagem, símbolo, caminho). A geração por modelo do ADR 0013 entra pela mesma porta e fica pendente.

## Alternativas consideradas

- Redigir o segredo e indexar o resto: descartado; uma redação falha vaza, e o arquivo inteiro raramente vale o risco.
- Comparar o commit em vez do SHA do conteúdo: reindexaria tudo a cada push.
- Detector de segredo por entropia: mais recall, mais falso positivo; os padrões atuais são de alta precisão e a lista é conservadora. O autor pode trocar por um scanner dedicado.

## Consequências

- Trecho não alterado mantém o commit em que foi indexado; o conteúdo, não a data, é o que a citação garante.
- Segredo com formato fora da lista passa; a varredura não substitui o scanner de segredos do CI do repositório-alvo.
- Linguagens além de Python e TypeScript caem no chunking por janela até receberem gramática.
