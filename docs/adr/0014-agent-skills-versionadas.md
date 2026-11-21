# 0014. Procedimentos como Agent Skills versionadas, com divulgação progressiva (F-14)

- **Status:** Proposto
- **Data:** 2026-11-21
- **Id no design doc:** F-14 (seção 13; detalhe nas seções 3A e 6.4.1)

## Contexto

Procedimentos da organização (escrever spec, ADR, revisão de segurança, migração segura, release, diagnóstico de incidente) precisam estar disponíveis aos agentes sem ocupar contexto fixo em toda sessão.

## Decisão

Os procedimentos viram skills em `.forja/skills/` no repositório-alvo (`spec-writing`, `adr-writing`, `security-review`, `safe-migration`, `release`, `incident-diagnosis`). No início da sessão o agente vê só nome e descrição de cada skill; corpo e scripts entram no contexto quando a tarefa pede. Mudar uma skill dispara os evals relacionados.

## Alternativas consideradas

- O design doc não registra alternativas para esta decisão. A preencher pelo autor antes de aceitar.

## Consequências

- Menos tokens fixos por sessão e procedimentos versionados com o código.
- Skills passam a ser código sob eval (ADR 0009).
