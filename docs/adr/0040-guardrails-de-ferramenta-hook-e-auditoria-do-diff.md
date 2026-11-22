# 0040. Guardrails de ferramenta, git do host sobre worktree hostil e fronteira do container

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

## A fronteira é o container, não a allowlist

A allowlist de argv e o PreToolUse reduzem o que o agente tenta e dão feedback rápido, mas não são fronteira de segurança: `python script.py`, `node -e`, `npx`, `uv run`, `make` e qualquer teste executam código arbitrário. Quem contém o agente é o container (sem root, `--read-only` exceto o worktree e `/tmp`, sem capabilities, rede só pelo proxy de allowlist, CPU, memória e pids limitados). Tudo que o agente faz que importa para o repositório é validado depois, no diff, por código.

## Git do host sobre um worktree que o container escreve

O worktree é montado com escrita no container, logo tudo nele é hostil, inclusive `.gitconfig`, `.gitattributes`, o ponteiro `.git` e repositórios aninhados. Um `git add` no host com filtro `clean` ou `credential.helper` configurados por ali executa comando no host e alcança o token do push (reproduzido no commit b867808). Regras (`AreaGit`, `RemotoGitHub`, `DockerSandbox`):

- O gitdir é resolvido na criação do worktree (antes de qualquer container), validado como filho de `<clone>/.git/worktrees/` e guardado fora do worktree, em `<raiz>/.meta/<nome>.json`. Toda chamada de git leva `GIT_DIR` e `GIT_WORK_TREE` explícitos; o ponteiro `.git` do worktree só é conferido (conteúdo idêntico ao registrado, aberto sem seguir link) e uma divergência recusa a operação. Sem registro, falha fechada.
- O ponteiro `.git` é montado somente leitura no container (`-v <wt>/.git:/workspace/.git:ro`); a restauração a partir do registro acontece ao descartar uma sessão.
- `HOME` é um diretório vazio fora do worktree, `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1`, `GIT_ATTR_NOSYSTEM=1`, `core.attributesFile=/dev/null`, hooks e fsmonitor desligados, `--no-ext-diff --no-textconv` no diff. Só a configuração do clone (do operador) e a do próprio código valem. O fetch e o push com token usam o mesmo caminho, então a configuração do worktree nunca é lida.
- `.git` aninhado (repositório falso, gitlink) em qualquer subdiretório e modo `160000` no índice são recusados antes de qualquer git que desça neles; o descarte os remove e usa `clean -ffdx`.
- Leitura e escrita de arquivo abrem cada componente do caminho com `O_NOFOLLOW` a partir de um descritor de diretório: link simbólico em qualquer nível é recusado.
- TOCTOU: o container (todos os processos, inclusive em segundo plano) é morto com `docker rm -f` (`Sandbox.quiescer`) antes de qualquer leitura ou git do host no worktree depois de código do repositório ter rodado, e a sessão seguinte usa um container novo (`reabrir`). Há teste de ordem sobre a linha do tempo das operações.
- Quem decide `passes` roda os testes num checkout limpo do commit (`ref=<sha>`), num container novo, depois do `init.sh` versionado: arquivo ignorado (`node_modules`, `.venv`, bytecode) ou deixado pela sessão não forja teste verde.

Alternativa avaliada e não adotada agora: rodar o git de staging (`add`, `diff`) num container sem rede e sem segredo, com o worktree e o gitdir montados. É mais forte (nem um defeito do git no host seria alcançável), mas move o `commit` para dentro do container, exige a imagem com git e o gitdir montado em leitura e escrita, o que reabre o problema do ponteiro. Fica como evolução se o git do host for considerado superfície grande demais.

## Chave da API no sandbox (risco aceito explicitamente)

A `ANTHROPIC_API_KEY` entra por `docker exec -e` no processo do CLI, que roda no mesmo container e uid do código do repositório. Qualquer teste ou script pode ler `/proc/<pid>/environ` do CLI e exfiltrar a chave por arquivo commitado ou pelos registries da allowlist. Por isso `FORJA_HARNESS` só liga com `FORJA_HARNESS_ACEITA_CHAVE_NO_SANDBOX=true` e com chave de gasto limitado e sem outros acessos. Correção de fundo (pendente): um proxy do modelo na rede interna que injeta a credencial (`ANTHROPIC_BASE_URL` apontando para ele e uma chave placeholder no container), ou uid separado para o CLI.

## Alternativas consideradas

- Só o hook: contornável por comando permitido. Só a auditoria: o agente gastaria a sessão inteira antes de descobrir.
- Sandbox de sistema de arquivos somente leitura para os testes: mais forte, mas o agente precisa rodar testes que escrevem caches.

## Consequências

- Falso positivo possível: refatorar teste existente exige a issue aprovada (`refatoracao_de_testes_aprovada`), que ainda não tem origem no fluxo (decisão do autor).
- `.github/workflows/**` e outros caminhos de alto risco não são bloqueados aqui: são o raio de impacto do M5.
