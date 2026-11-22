# 0035. Ativação só em repositórios habilitados, com nome validado no ponto de entrada

- **Status:** Proposto
- **Data:** 2026-11-22
- **Id no design doc:** seção 7 ("repositório habilitado") e 9.4

## Contexto

O nome do repositório vem de um payload de webhook e acaba como caminho de clone, nome de branch e destino de escrita.

## Decisão

`AtivarEntrega` ignora (e registra) comandos cujo repositório não tem a forma `dono/nome` segura (`forja.domain.seguranca.repositorio_valido`) ou não está em `FORJA_REPOS_HABILITADOS`. Lista vazia recusa tudo (falha fechada). O resolvedor de clones repete a validação e recusa caminhos fora da raiz, inclusive por symlink.

## Alternativas consideradas

- Habilitar por instalação do GitHub App: a instalação já limita, mas a Forja não deve depender só da configuração do App.

## Consequências

- Um repositório novo exige entrada explícita na configuração.
