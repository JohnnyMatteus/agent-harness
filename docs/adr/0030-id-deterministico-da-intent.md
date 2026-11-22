# 0030. Id determinístico da Intent: SHA-256 de tipo, repositório e identificador da origem

- **Status:** Proposto
- **Data:** 2026-11-21
- **Id no design doc:** não numerado (seção 7 pede "id determinístico"; M1-02 deixa a fórmula para decisão do autor)

## Contexto

"Um workflow por intenção" (seção 7) exige que o mesmo evento, entregue duas vezes ou por caminhos diferentes, resulte no mesmo id. O id também vira nome de branch (`forja/<intent-id>-<slug>`), pasta `.forja/<intent-id>/` e id do workflow Temporal. O design doc não define a fórmula.

## Decisão

`intent_id = sha256("<tipo>:<dono/repo em minúsculas>#<identificador>")[:16]` em hexadecimal. Para issues do GitHub o identificador é o número da issue; para a CLI e para bandas, o identificador da execução ou do incidente. Título e corpo não entram na fórmula, então editar a issue não cria outra intenção.

## Alternativas consideradas

- Número da issue puro: colide entre repositórios.
- `dono/repo#numero` como id legível: caracteres inválidos em branch e caminho, e vaza o nome do repositório em logs de métricas.
- UUID v5 sobre a mesma chave: equivalente, mas 36 caracteres e sem ganho; o hash curto cabe bem em branch e commit trailer.
- Incluir o título: edições legítimas gerariam duplicatas.

## Consequências

- Idempotência de graça: `ReceberIntent` consulta o id antes de criar.
- 16 hex (64 bits) tornam colisão irrelevante na escala de um GitHub App.
- Renomear ou transferir o repositório gera outro id; aceito no M1 e registrado como limitação.
