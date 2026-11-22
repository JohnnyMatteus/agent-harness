# 0041. Memória por repositório em Postgres e context editing no Avaliador

- **Status:** Proposto
- **Data:** 2026-11-22
- **Id no design doc:** seção 6.4.2; ADR 0012 (M4)

## Contexto

O memory tool e o context editing são recursos da Messages API; o Agent SDK não expõe context editing (o CLI compacta sozinho). A memória escrita por um agente volta ao prompt de sessões futuras: é um canal de persistência para texto injetado.

## Decisão

- **Backend:** `ArmazemDeMemoria` (porta) com `ArmazemPostgres` (tabela `memoria_repositorio`) e versão em memória para testes. `MemoriaDoRepositorio` implementa os comandos do memory tool (`view`, `create`, `str_replace`, `insert`, `delete`, `rename`). O repositório é fixado na construção: nenhum argumento do agente o altera.
- **Uso:** o Executor acessa pela ferramenta MCP em processo `memoria`; o Avaliador, pelo memory tool nativo (`memory_20250818`). O conteúdo entra no prompt como dado delimitado, e `dado_nao_confiavel` impede fechar a tag.
- **Tetos e saneamento** (`forja.domain.memoria`): caminho só em `/memories`, 4 níveis, `.md`/`.txt`; 8 KB por arquivo, 50 arquivos, 100 KB por repositório; controle removido e segredos redigidos ao gravar.
- **Context editing:** o Avaliador roda na Messages API com `context_management` (`clear_tool_uses_20250919`, beta `context-management-2025-06-27`), `exclude_tools=["memory"]`, gatilho, retenção e mínimo de limpeza configuráveis por modelo (`EstrategiaDeContexto`). Os nomes dos campos foram conferidos contra os tipos do SDK `anthropic` instalado e há teste que falha se divergirem.
- **Reset com handoff** é o desenho do Executor: cada sessão começa limpa e lê `progress.md`, o contrato e o log; a compactação fica com o SDK.

## Pendentes do autor

Valores de gatilho e retenção do context editing e a escolha entre compactação e reset por modelo (hoje: reset, sem medição); curadoria da memória (hoje só tetos, sem expiração).

## Consequências

- Memória envenenada persiste até alguém apagar; mitigação: tetos, segredos redigidos, dado delimitado e isolamento por repositório.
- O Executor não tem context editing (limite do Agent SDK); sessões curtas e `max_turns` fazem o papel.
