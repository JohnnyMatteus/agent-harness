# 0034. Escrita externa: dry-run por padrão e idempotência atômica por chave

- **Status:** Proposto
- **Data:** 2026-11-22
- **Id no design doc:** reforça a seção 7 (um workflow por intenção) e a 9.4

## Contexto

Activities do Temporal são retentadas; uma escrita no GitHub repetida vira comentário duplicado. Em desenvolvimento, uma configuração errada não pode escrever num repositório real.

## Decisão

- Toda escrita externa passa pela porta `Publicador`. A implementação `PublicadorGitHub` é dry-run a menos que `FORJA_PUBLICAR=true`; em dry-run só registra em log.
- Idempotência por chave determinística (`<intent-id>:<ponto>`): `SET NX` no Redis com lease de 10 min reivindica a chave de forma atômica; sucesso grava `concluida` por 30 dias; falha libera a chave; outra tentativa em curso levanta `PublicacaoEmAndamento` (o Temporal retenta).
- Todo corpo é neutralizado na saída (menções `@` quebradas; `<` escapado; imagens, links e definições markdown removidos e `://` e `www.` defangados, porque o GitHub busca imagens sozinho e `![](https://x/?dados)` vazaria dados; segredos redigidos; tamanho limitado) e o destino é validado.

## Alternativas consideradas

- Procurar o comentário já publicado antes de escrever (marcador no corpo): cobre a janela de queda entre a escrita e o `concluir`, mas exige listar comentários paginados a cada publicação. Fica como melhoria.
- Confiar só na retentativa limitada do Temporal: não impede duplicata.

## Consequências

- Janela residual: se o processo morrer depois de o GitHub aceitar a escrita e antes de `concluir`, a chave expira em 10 min e a retentativa duplica. Aceito até existir a verificação por marcador.
- Redis passa a ser dependência do worker, além do gateway.
