# 0039. Build de longa duração: estado na branch, git no workflow e `passes` decidido por código

- **Status:** Proposto, com pontos pendentes do autor (ver abaixo)
- **Data:** 2026-11-22
- **Id no design doc:** seções 5.3 e 5.3.1; ADRs 0002 e 0011 (M4)

## Contexto

O Build precisa avançar por várias sessões sem memória, sem confiar na palavra do agente, e sem dar ao agente credencial ou git (ADR 0007, 0036).

## Decisão

- **Continuidade na branch remota** da entrega: `feature_list.json`, `progress.md`, `init.sh` e `sprint-contract.json` (em `.forja/<intent-id>/`), mais o git log. Cada passo roda num sandbox novo: busca a branch (`RemotoGitHub.buscar`), trabalha, commita e envia (`enviar`, só `forja/*`, sem force, token por `GIT_CONFIG_*` e nunca em argumento). Sem `FORJA_PUBLICAR=true` o harness não sobe (falha de configuração), porque sem remoto o estado não atravessa sessões.
- **Git é do workflow**, no host (`AreaGit`), com `GIT_DIR` explícito resolvido na criação e o container parado antes de qualquer leitura (ADR 0040): o worktree montado no container não tem o `.git` do clone, e o agente não precisa dele. O agente edita arquivos e roda comandos de teste; o código audita o diff, descarta a sessão se houver violação e só então commita, com os trailers `Intent-Id`, `Run-Id` e `Co-Authored-By`.
- **Inicializador** (sem ferramenta) propõe funcionalidades, comandos de setup e teste de fumaça; o código valida cada comando (allowlist) e escreve os arquivos, inclusive o `init.sh`.
- **Bloco** (até `FORJA_TAMANHO_DO_BLOCO` funcionalidades, padrão 3): o Executor propõe o contrato, o Avaliador revisa até haver acordo (3 rodadas, senão `SemAcordoNoContrato`); o contrato é commitado e os limiares vêm do código, não do agente. Uma sessão do Executor por funcionalidade, com os passos 1, 2 e 4 da seção 5.3 feitos por código (branch, `progress.md` e log, `init.sh` mais teste de fumaça antes da sessão).
- **`passes: true`** só por `FeatureList.com_passes`, chamado pelo código quando (a) o Avaliador aprovou o bloco com todas as notas no limiar e (b) o grader de código viu o comando de teste da própria funcionalidade sair com 0, ambos num checkout limpo do commit, num container novo. `exigir_so_passes_mudou` garante que mais nada mudou e que nada volta de `true` para `false`. Isto é mais estrito que o design doc: o Executor nunca escreve `feature_list.json`, nem o campo `passes`.
- **Máquina de estados:** Build (blocos) -> `concluir_build` -> Test (verificação final de todos os testes num sandbox novo) -> `registrar_verificacao`. Verde: Review, PR em rascunho e fim da parte do M4 (`Desfecho.VERIFICADA`; revisão é o M5). Vermelho: conta ciclo (ADR 0031) e a entrega falha para um humano. Sem funcionalidade aprovada por 3 blocos seguidos, também.
- **Sessão suja ou sem `progress.md` atualizado** é descartada (`reset --hard` e `clean`), como o hook de parada da seção 9.2.

## Pendentes do autor (modo par, seção 14)

Rubrica, limiares e exemplos de calibração do Avaliador: os valores no código são provisórios (7 em todos os critérios; 3 exemplos no prompt) e não foram calibrados. Também: tamanho do bloco, rodadas máximas, e o modelo do Avaliador (`FORJA_MODELO_AVALIADOR`, sem default).

## Limitações

- **Submódulo (gitlink) não é suportado:** o harness recusa a sessão se a árvore da base ou do HEAD tem modo 160000, e recusa `.git` aninhado (ADR 0040).
- **O modo Docker nunca rodou contra Docker real:** o `DockerSandbox` (inclusive o `.git` somente leitura, o `rm -f` e o `reabrir`), o modo `docker` do lançador e a imagem `forja-agente` só foram exercitados com docker falso; os testes de ponta a ponta usam sandbox local com git real.

- Regressão detectada só na verificação final encerra a entrega (não reabre funcionalidades).
- Duas implementações concorrentes para issues `hard` (seção 5.3.1) não foram feitas.
- O Avaliador não usa Playwright: testa por comandos no sandbox (UI exige imagem com navegador).
- Imagem `forja-agente` (`infra/sandbox/Dockerfile.agente`) e o modo `docker` do lançador não foram construídos nem exercitados contra Docker real; os testes usam sandbox local e git real.
