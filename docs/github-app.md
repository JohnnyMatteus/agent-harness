# GitHub App da Forja: registro e configuração

O registro do App é manual (pendência do autor). Nada aqui entra no Git: a chave privada e os segredos ficam fora do repositório.

## 1. Registrar o App

Em Settings > Developer settings > GitHub Apps > New GitHub App (na conta ou organização dona):

- **Webhook URL:** `https://<host-da-forja>/webhooks/github` (em desenvolvimento, um túnel como smee.io ou cloudflared).
- **Webhook secret:** string aleatória longa (`openssl rand -hex 32`). Vira `FORJA_GITHUB_WEBHOOK_SECRET`.
- **Permissões de repositório (mínimas, ADR 0007):** Contents (read and write), Pull requests (read and write), Issues (read and write), Checks (read and write), Metadata (read-only). Nenhuma permissão de conta ou organização.
- **Eventos assinados:** Issues, Issue comment (e, nos marcos seguintes, Pull request e Check suite).
- **Where can this app be installed:** Only on this account.

## 2. Chave privada

Em "Private keys", gere uma chave e guarde o `.pem` num gerenciador de segredos. Entregue à Forja de uma das formas:

- `FORJA_GITHUB_APP_PRIVATE_KEY_FILE=/run/secrets/forja-app.pem` (arquivo montado; preferido);
- `FORJA_GITHUB_APP_PRIVATE_KEY` com o PEM, aceitando `\n` literais.

`*.pem` e `*.key` estão no `.gitignore`. Se a chave vazar, revogue-a na página do App e gere outra.

## 3. Variáveis de ambiente

| Variável | Uso |
| --- | --- |
| `FORJA_GITHUB_APP_ID` | id numérico do App |
| `FORJA_GITHUB_APP_PRIVATE_KEY_FILE` ou `FORJA_GITHUB_APP_PRIVATE_KEY` | chave privada |
| `FORJA_GITHUB_WEBHOOK_SECRET` | segredo do webhook (HMAC) |
| `FORJA_GITHUB_MAX_CORPO_BYTES` | limite do corpo (padrão 1 MiB) |
| `FORJA_PANICO_TOKEN_SHA256` | SHA-256 do token do botão de pânico (ADR 0019): `printf %s "$TOKEN" \| shasum -a 256` |

## 4. Instalar

Instale o App só nos repositórios habilitados. A Forja descobre a instalação por repositório e pede um token de instalação de curta duração (1 h, reaproveitado até 2 min antes de expirar), restrito às permissões acima. Nenhum token pessoal é usado.

## Testes

Os testes não usam rede: payloads em `tests/fixtures/github/` são anonimizados (repositório fictício `acme-demo/loja-exemplo`), as respostas da API são gravadas (`api_*.json`) e a chave RSA é gerada em memória a cada execução.
