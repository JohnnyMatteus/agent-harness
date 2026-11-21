# 0001. AI-native SDLC como máquina de estados com artefatos versionados no repositório-alvo (F-01)

- **Status:** Proposto
- **Data:** 2026-11-21
- **Id no design doc:** F-01 (seção 13; detalhe nas seções 3, 5.1 e 5.2)

## Contexto

O gargalo da engenharia com agentes mudou do código para planejamento, revisão e deploy (seção 1). Agentes trabalham em turnos sem memória, então a continuidade precisa morar fora do contexto do modelo. A cadeia de commits deve servir de trilha de auditoria.

## Decisão

Cada intenção é uma `Entrega` conduzida por uma máquina de estados (Plan, Design, AguardandoSpec, Build, Test, Review, AguardandoHumano, Deploy, Maintain; seção 5.1). Cada etapa commita um artefato que a próxima lê (`intent.md`, `spec.md`, `plan.md`, `feature_list.json`, `progress.md`, `review.md`, `bands.yaml`, `incident.md`), em `.forja/<intent-id>/` na branch da entrega. Os portões são: confirmação do `intent.md` por quem pediu, humano resolve os pontos em aberto da spec antes do Build, verificação verde no Test e humano no Deploy quando o raio de impacto exige. Os commits levam os trailers `Intent-Id`, `Run-Id` e, quando houver, `Approved-By`.

## Alternativas consideradas

- O design doc não registra alternativas para esta decisão. A preencher pelo autor antes de aceitar.

## Consequências

- Retomar uma entrega depois de falha ou troca de sessão é ler os artefatos e o git log.
- Auditoria pela cadeia de commits, sem banco de auditoria separado para o que é artefato.
- A máquina de estados e as regras de transição são núcleo do autor (modo par, seção 14).
- O repositório-alvo recebe arquivos `.forja/` em cada branch de entrega.
