# 0046. Eficiência de ferramentas: medição e regra para ligar o tool search (M7)

- **Status:** Proposto
- **Data:** 2026-11-22
- **Id no design doc:** F-15 (ADR 0015), seção 6.4 e M7

## Contexto

O ADR 0015 propõe tool search, programmatic tool calling e code execution com MCP para reduzir tokens. O M7 pede medir antes de construir. O catálogo hipotético do rascunho (vários servidores MCP) não existe: o servidor MCP knowledge não é dado ao agente (o segredo do token não pode estar no ambiente dele), e os agentes de hoje recebem poucas ferramentas.

## Medição (estimativa: caracteres do JSON da definição / 4; teste `tests/infrastructure/agents/test_tokens_de_ferramentas.py`)

| Agente | Ferramentas que recebe | Tokens de definição (estimados) |
| --- | --- | --- |
| Intérprete, Spec, Planner, revisores, diagnóstico | nenhuma (`tools=[]`, escrita negada) | 0 |
| Executor (M4) | Read, Glob, Grep, Write, Edit (nativas do CLI) + `mcp__sandbox__exec` + `mcp__memoria__memoria` + `mcp__skills__skill` | nossas 3: 254 (exec 63, memoria 140, skill 51); as 5 nativas não foram medidas |
| Avaliador (M4) | `memory` (tipo da API), `executar_comando`, `ler_arquivo`, `registrar_avaliacao` | 219 (12 + 62 + 43 + 102); o texto interno da ferramenta de memória não foi medido |

Não medi as definições nativas do CLI nem usei a API de contagem de tokens (exigiria a chave): o número é uma estimativa por tamanho de texto, boa para comparar com a mesma régua e não como contagem do tokenizador.

## Decisão

- **Tool search não é ligado agora.** São 8 ferramentas no pior caso e algumas centenas de tokens nossos (2,5% do limiar de 10 mil tokens a partir do qual a Anthropic recomenda tool search; também abaixo de 10 ferramentas). A própria ferramenta de busca é uma definição a mais em todo turno e adiciona uma ida e volta: custaria perto do que economiza. Não há módulo de busca no código (o rascunho BM25 não foi commitado) e não há "antes e depois" a reportar porque não há o que mudar.
- **Quando ligar (regra):** quando um agente com ferramentas passar de ~10 ferramentas ou de ~10 mil tokens de definição, ou quando houver vários servidores MCP expostos ao agente. O teste de medição falha bem antes: com 10 ou mais ferramentas ou com 10% do limiar de tokens (1 000), para forçar a reavaliação.
- **Como ligar, sem código novo:** o CLI fixado (claude-agent-sdk 0.2.187, CLI 2.1.330) já traz tool search nativo (`ToolSearch`, `defer_loading`, `ENABLE_TOOL_SEARCH`; os tipos `tool_search_tool_regex` e `tool_search_tool_bm25` estão no SDK). Usar o nativo, não um BM25 próprio. Ligar exige repassar `ENABLE_TOOL_SEARCH` pelo lançador (que filtra o ambiente) e permitir `ToolSearch` na política: hoje o `decidir_ferramenta` o nega por padrão.
- **Busca nunca amplia permissão:** o que o agente descobrir só roda se estiver na allowlist (`allowed_tools` e `decidir_ferramenta`) e passa pelo mesmo PreToolUse; a negação vai para a auditoria (`forja_bloqueios_hook_total`). Há teste de que uma ferramenta "descoberta" fora da lista é negada e auditada.
- **Programmatic tool calling e code execution com MCP: não feitos.** Exigem o agente escrever e executar código que chama as ferramentas; o container do Executor tem a chave da API (ADR 0040) e a fronteira é o container, não a allowlist. Criar execução de código nova ou expor MCP como API de código no sandbox é decisão do autor, com este risco: um script escrito pelo agente passa a ter uma superfície de ferramentas fora do PreToolUse. O que cabe hoje, se for preciso, é um lote determinístico escrito por código, somente leitura, no workflow, sem o agente escrever código.

## Consequências

- Sem mudança de comportamento nem de custo; o ganho do M7 é a decisão registrada, o teste que a vigia e a regra de quando ligar.
- Risco aceito: a medição não inclui as definições nativas do CLI, que não podemos reduzir de qualquer forma.
