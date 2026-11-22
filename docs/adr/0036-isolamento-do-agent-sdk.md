# 0036. Isolamento do Agent SDK: sem ferramenta no host; com ferramenta, só dentro do sandbox

- **Status:** Proposto
- **Data:** 2026-11-22
- **Id no design doc:** seções 9.2, 9.4 e 5.4; corrige o ADR 0033 original

## Contexto

O Agent SDK executa o CLI do Claude como subprocesso do worker. Três fatos da versão instalada (0.2.187) moldam o risco:

1. `allowed_tools=[]` só deixa de pré-aprovar; Read, Grep e Glob continuam disponíveis. Só `tools=[]` (`--tools ""`) remove as ferramentas.
2. O SDK mescla `os.environ` do worker no ambiente do CLI e `options.env` só acrescenta ou sobrescreve; não há como remover uma variável. Um agente com leitura de arquivo lê `/proc/self/environ` e o workflow publicaria o segredo.
3. Sem `setting_sources` explícito, o CLI pode carregar `.claude/settings.json` (hooks executam no host), CLAUDE.md e `.mcp.json` do repositório, que é conteúdo não confiável.

## Decisão

- Agente sem ferramenta (eco, Intérprete): `tools=[]`, `setting_sources=[]`, `mcp_servers={}` com `strict_mcp_config`, `cwd` e `HOME` em diretórios vazios e descartáveis, nunca o repositório. Não usa sandbox porque não tem o que isolar.
- Ambiente do processo do agente: o SDK nunca executa o CLI direto; `cli_path` é `lancador_cli.py` (só stdlib), que recompõe o ambiente com uma allowlist (`ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `CLAUDE_CODE_*`, `CLAUDE_AGENT_SDK_*`, contexto de trace). Segredo do webhook, do GitHub App, do Redis e do pânico não chegam ao agente.
- Agente com ferramenta (M3 em diante): o CLI roda dentro do container do `DockerSandbox` (modo `docker` do lançador: `docker exec -i`, só nomes da allowlist repassados, valores fora do argv), com `setting_sources=[]`, sem credencial do GitHub e com egress só pela allowlist. As ferramentas nativas do host nunca tocam o repositório.
- MCP knowledge: o processo do MCP (que recebe `FORJA_KNOWLEDGE_TOKEN_SECRET` e `DATABASE_URL`) nunca é filho do agente nem roda no sandbox dele; o worker o sobe fora e entrega ao agente só o transporte ou o token. O Spec do M3 consulta o conhecimento por código, pela porta `BuscaDeConhecimento`, e passa só trechos ao agente. Os dois valores não estão na allowlist e o teste de ambiente efetivo os inclui.
- Publicação: todo texto vindo do agente passa por `neutralizar_texto` antes de ir ao GitHub (ADR 0034).

## Alternativas consideradas

- Remover variáveis via `options.env`: impossível nesta versão do SDK; zerar nomes conhecidos deixaria passar os desconhecidos.
- Rodar o SDK Python inteiro no container: mais isolamento, mas exige o SDK e o loop de hooks na imagem; o `docker exec` do CLI mantém hooks e ferramentas MCP em processo no host, que só decidem, sem tocar arquivo.

## Consequências

- A chave `ANTHROPIC_API_KEY` chega ao processo do agente (é necessária). Com ferramenta, um prompt injection poderia lê-la; mitigação: egress só para a API do modelo, redação de segredos na publicação e chave com limite de gasto. Risco residual aceito, a confirmar com o autor.
- O modo `docker` exige uma imagem com o CLI `claude` (`Dockerfile.agente`, não construída no CI) e não foi exercitado contra Docker real.
- Autenticação por login interativo (`~/.claude`) não funciona: o HOME é descartável. Usa-se chave de API.
- O comportamento depende de `tools=[]` e `--setting-sources=` na versão do SDK; `tests/infrastructure/agents/test_isolamento.py` verifica o comando real montado pelo SDK e quebra se mudar.
