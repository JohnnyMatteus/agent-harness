# 0044. Skills da organização com divulgação progressiva

- **Status:** Proposto
- **Data:** 2026-11-22
- **Id no design doc:** seção 6.4.1; M5

## Decisão

- Skill é `SKILL.md` com frontmatter `name` (igual ao nome da pasta) e `description`. No contexto do Executor entram só nome e descrição; o corpo carrega pela ferramenta `skill`, que aceita apenas nomes do catálogo (nunca caminho) e devolve o texto como dado delimitado.
- Cinco skills padrão acompanham a Forja (spec-writing, adr-writing, security-review, safe-migration, release). O repositório-alvo pode acrescentar ou sobrescrever em `.forja/skills/<nome>/SKILL.md`, lidas da branch padrão e listadas em `.forja/skills.txt`; skill inválida é ignorada, nunca carregada pela metade.
- O revisor de segurança recebe a skill `security-review` por código.

## Limitações

- A skill de diagnóstico de incidente (`incident-diagnosis`) entra com o M6. Mudar uma skill disparar os evals relacionados é do M8.
