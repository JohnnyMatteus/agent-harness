# 0033. Binário `forja` com raiz de composição única; eco como etapa Plan do M1

- **Status:** Proposto
- **Data:** 2026-11-22
- **Id no design doc:** não numerado (seções 4.4 e 12, M1)

## Contexto

Até aqui as peças do M1 (gateway, Temporal, sandbox, agente eco, GitHub) existiam soltas e só os testes as ligavam. Uma feature que ninguém chama não é feature.

## Decisão

- `forja serve` sobe o gateway FastAPI (webhooks, `/panico`, `/metrics`); `forja worker` sobe o worker do Temporal com as activities. Os dois processos compartilham só Temporal e Redis.
- A única raiz de composição é `forja/interfaces/cli/composicao.py`; nenhum outro módulo instancia adaptadores. A configuração vem do ambiente (`Ajustes`, `GitHubConfig`) e é documentada em `.env.example`.
- O worker roda no host (ou onde houver acesso ao Docker), não em container do compose: ele cria containers irmãos e dar o socket do Docker a um container equivale a root no host.
- No M1 a etapa Plan é o agente eco: uma activity chama o agente (sem ferramenta, sem sandbox: ver ADR 0036) e devolve o texto; quem publica é o workflow, em outra activity (ADR 0007). O Intérprete do M3 ocupa o mesmo lugar. O sandbox só entra para agentes com ferramenta.
- O repositório-alvo (usado a partir do M3) é um clone local em `FORJA_REPOS_DIR/<dono>/<nome>`, preparado pelo operador; o nome vem do webhook e é validado antes de virar caminho.

## Alternativas consideradas

- Typer no CLI: não há subcomandos suficientes para justificar a dependência; `argparse` basta.
- Clonar o repositório dentro da activity com o token de instalação: exige credencial real e passa o token por argumento de processo; fica para quando houver um helper de credencial git seguro.

## Consequências

- O clone e a atualização do repositório são responsabilidade do operador até haver clonagem automática.
- A imagem de container do gateway não existe ainda; `uv run forja serve` é o caminho suportado.
