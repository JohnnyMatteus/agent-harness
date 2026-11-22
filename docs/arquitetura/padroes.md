# Padrões e princípios aplicados

Registro dos padrões de projeto e dos princípios SOLID usados, por contexto. Cada bloco diz o padrão, onde está e por quê.

## Knowledge (M2)

| Padrão ou princípio | Onde | Por quê |
| --- | --- | --- |
| Ports and Adapters | `application/portas/knowledge.py` (porta) e `infrastructure/knowledge/` (adaptadores) | O caso de uso não sabe se o índice é Postgres ou memória, nem se o embedding é falso ou de modelo |
| Dependency Inversion | `IndexarRepositorio` recebe fonte, chunker, embedder, gerador e índice por construtor | Trocar uma peça não mexe nas outras |
| Open/Closed | Nova linguagem entra por gramática no chunker; novo gerador de contexto, por outra implementação da porta | Estender sem alterar o caso de uso |
| Value Object | `Escopo`, `Trecho` (imutáveis, validados na criação) | O isolamento por organização e repositório não pode ser esquecido nem alterado |
| Função pura no domínio | `fundir_rrf` | Regra de fusão testável sem infraestrutura |
| Idempotência por versão de conteúdo | `IndexarRepositorio` | Reexecutar (webhook repetido, retry do Temporal) não duplica nem reescreve |
