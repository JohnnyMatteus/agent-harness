---
name: security-review
description: Checklist de revisão de segurança (OWASP) para um diff: entrada, autenticação, segredos, injeção.
---
# Revisão de segurança

- Entrada externa chega validada por schema antes de virar caminho, comando, consulta ou texto publicado?
- Autenticação e autorização checadas no ponto de entrada, e testadas por ele?
- Segredo em código, log, mensagem de erro ou fixture?
- Injeção: SQL, comando, caminho, template, prompt. Dependência nova: origem e versão.
