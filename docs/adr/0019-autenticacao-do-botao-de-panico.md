# 0019. Autenticação do botão de pânico: bearer de alta entropia, só o hash na configuração

- **Status:** Proposto
- **Data:** 2026-11-21
- **Id no design doc:** ponto em aberto do M1-08 (seção 7: "botão de pânico global")

## Contexto

`POST /panico` cancela todos os workflows e destrói os sandboxes. É a ação mais destrutiva da API e precisa ser acionável em segundos por quem opera a Forja, inclusive a partir de um celular. Na v1 há um único dono (sem multiusuário). O endpoint nunca deve ficar aberto, nem depender dos webhooks do GitHub: um comentário de issue é entrada não confiável (seção 9.4).

## Decisão

- O dono gera um token aleatório de pelo menos 32 bytes e o guarda em um gerenciador de segredos.
- A configuração (`FORJA_PANICO_TOKEN_SHA256`) guarda só o SHA-256 hexadecimal do token; o servidor nunca tem o token em claro, então um vazamento de configuração ou de log não permite acionar o pânico.
- A requisição envia `Authorization: Bearer <token>`. O servidor calcula o SHA-256 do que chegou e compara em tempo constante (`hmac.compare_digest`). Como o token tem alta entropia, um hash rápido é suficiente (não há ataque de dicionário).
- Falha de autenticação responde 401 sem detalhes e é registrada; cada acionamento válido registra quantos workflows foram cancelados.
- O endpoint só é exposto atrás de TLS; em produção, restringir também por rede (listener interno ou allowlist de IP) como defesa em profundidade.
- Se o hash não estiver configurado, o endpoint recusa tudo (falha fechada).

## Alternativas consideradas

- Login do GitHub (OAuth) com verificação de que o usuário é o dono: melhor para vários operadores e trilha de auditoria por pessoa, mas adiciona fluxo de login, sessão e dependência do GitHub justamente quando se quer parar tudo. Candidata para quando houver mais de um operador.
- mTLS com certificado de cliente: forte, porém pesado para operar a partir de um celular.
- Allowlist de IP apenas: frágil com IP móvel e insuficiente sozinha.
- Comando `/forja panic` em comentário: descartado, o canal é controlado por terceiros e entra como dado não confiável.

## Consequências

- Rotação do token é trocar o hash na configuração.
- Sem identidade por operador: a trilha de auditoria diz "o dono", não quem. Aceitável com um dono.
- Um token vazado do lado do cliente permite parar tudo (impacto de disponibilidade, não de integridade); mitigado por TLS, restrição de rede e rotação.
