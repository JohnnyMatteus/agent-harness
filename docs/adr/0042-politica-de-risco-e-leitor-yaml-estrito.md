# 0042. Política de risco como código e leitor de YAML estrito (sem dependência nova)

- **Status:** Proposto, com decisão pendente do autor (formato e dependência)
- **Data:** 2026-11-22
- **Id no design doc:** seções 9.1 e 14 (política de raio de impacto é núcleo do autor); M5

## Contexto

`.forja/policy.yaml` e `.forja/bands.yaml` vêm do repositório-alvo (conteúdo não confiável). O projeto não tem biblioteca YAML e instalar dependência exige atualizar o lock (rede e disco).

## Decisão

- `Politica.de_dict` (domínio) valida o conteúdo: chaves de topo `risk_tiers` e `budgets`, tiers `high`, `medium`, `low`, tipos e tetos; chave desconhecida é recusada. Sem arquivo, ilegível ou inválido: `Politica.padrao_fechado()` (nada é baixo risco, logo toda entrega passa por um humano).
- Tier final = o maior entre caminhos tocados, labels e achados dos revisores; caminho fora de qualquer tier é médio; `max_diff_lines` acima do limite eleva o médio a alto; sem caminhos, alto. `Tier.exige_humano` vale para médio e alto. Há teste de propriedade: acrescentar caminho de alto risco nunca baixa o tier.
- O casamento de glob preserva a semântica original (`**/` casa zero ou mais diretórios, `**` casa qualquer coisa inclusive `/`, `*` e `?` não casam `/`; logo `deploy/**.tf` casa `deploy/prod/main.tf`) e roda por programação dinâmica, O(padrão x caminho), sem regex nem backtracking: o padrão é do repositório-alvo e uma regex com `**` encadeados seria exponencial. Há teste diferencial exaustivo contra a regex antiga em corpus curto e teste de padrão adversário sob prazo.
- Regra geral: se a Forja não viu tudo, não é risco baixo. Caminho acima de 400 caracteres é alto. `.github/**` e `.forja/**` (exceto os artefatos da própria intenção, `.forja/<intent-id>/`) são sempre altos, por código e independentes da política, porque mudam a régua e os checks. Diff cortado pelo compare (300 arquivos) é alto; diff que o revisor não viu inteiro é no mínimo médio (ADR 0043). Rename conta o caminho de origem (`previous_filename`).
- A política vem da **branch padrão**, nunca da branch da entrega, e `.forja/` é caminho protegido para o agente (ADR 0040).
- Leitor `yaml_estrito`: subconjunto (mapas e listas em bloco, listas de escalares em linha, escalares). Recusa âncoras, tags, documentos múltiplos, blocos `|` e `>`, mapa em linha, tabulação, chave repetida e aninhamento acima de 8 níveis.

## Pendente do autor

Trocar o leitor por PyYAML (`safe_load`) quando o lock puder ser atualizado, ou adotar TOML (stdlib `tomllib`) para a política; os valores padrão de orçamento (5 USD por intenção, 20 sessões) e o tier de caminho desconhecido (médio) também são dele.

## Consequências

- Um `policy.yaml` com sintaxe YAML válida mas fora do subconjunto é tratado como inválido e fecha a política, em vez de abrir.
