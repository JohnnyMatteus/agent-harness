# 0040. Guardrails de ferramenta: PreToolUse com negação por padrão e auditoria do diff

- **Status:** Proposto
- **Data:** 2026-11-22
- **Id no design doc:** seções 9.2 e 15 (agente trapaceia); M4

## Contexto

O hook de PreToolUse vê `Write`, `Edit` e as outras ferramentas, mas não vê o que um comando permitido faz: `python`, `pytest` ou um script do repositório escrevem arquivos à vontade. Só o hook não segura "não editar teste existente".

## Decisão

- Duas camadas, ambas código em `forja.domain.guardrails`:
  1. **PreToolUse** (`hook_pre_tool_use`, registrado com `on_failure="block"` e `permission_mode="dontAsk"`): negação por padrão. Permite leitura e escrita dentro de `/workspace`, `mcp__sandbox__exec` com argv na allowlist e a ferramenta de memória; nega o resto (inclusive `Bash`, `WebFetch`). Bloqueia: `.git`, arquivos de segredo, link simbólico, `feature_list.json`, contrato, `init.sh`, artefatos de `.forja/` (exceto o `progress.md` da entrega), teste que já existia na base da sessão.
  2. **Auditoria do diff depois da sessão** (`auditar_mudancas`): as mesmas regras sobre `git diff --cached --raw` contra a base, mais modo `120000` (link). Qualquer violação descarta a sessão inteira.
- O shell do agente é a ferramenta própria `exec` (argv, sem shell), que reaplica a política por dentro; `git`, `curl`, `rm` e afins não estão na allowlist, e `python` só como `-m pytest|unittest|pip|venv`.
- Antes de cada sessão, links simbólicos que saem do worktree recusam a sessão; os internos ficam protegidos contra escrita.
- Bloqueios e descartes alimentam `forja_bloqueios_hook_total`.

## Alternativas consideradas

- Só o hook: contornável por comando permitido. Só a auditoria: o agente gastaria a sessão inteira antes de descobrir.
- Sandbox de sistema de arquivos somente leitura para os testes: mais forte, mas o agente precisa rodar testes que escrevem caches.

## Consequências

- Falso positivo possível: refatorar teste existente exige a issue aprovada (`refatoracao_de_testes_aprovada`), que ainda não tem origem no fluxo (decisão do autor).
- `.github/workflows/**` e outros caminhos de alto risco não são bloqueados aqui: são o raio de impacto do M5.
