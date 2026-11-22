# 0038. Portões humanos por sinal; rejeição encerra o workflow sem aresta nova na máquina de estados

- **Status:** Proposto, com decisão pendente do autor (ver abaixo)
- **Data:** 2026-11-22
- **Id no design doc:** seções 5.1, 5.2 (portões), 7 (comandos) e 7.1

## Contexto

O portão de spec (AguardandoSpec) e a confirmação do intent precisam de decisão humana durável. O design doc não define o que acontece quando o humano rejeita, e a máquina de estados é núcleo do autor.

## Decisão

- Comandos em comentário: `/forja confirm`, `/forja approve`, `/forja reject <motivo>` (além do `/forja stop` existente). O tradutor reconhece só linha inteira começando por `/forja` (citação com `>`, bot e menção no meio da frase não contam); o motivo é texto não confiável, limitado a 500 caracteres e neutralizado ao publicar.
- Só quem tem escrita no repositório sinaliza (mesma regra de ativação, seção 7). Cada comando vira um sinal do `DeliveryWorkflow`.
- Há dois portões, `intent` e `spec`. O portão é aberto antes de o resumo ser publicado, e qualquer sinal que chega com o portão fechado é descartado, não guardado: ninguém confirma ou aprova o que ainda não viu, e uma aprovação antecipada não vale para um portão futuro.
- `confirm` só vale no portão `intent` e só de quem pediu: o autor da issue ou quem aplicou o label (design doc, seção 5.2: "quem pediu confirma o resumo"; a leitura de "quem pediu" é a decisão registrada aqui). `approve` só vale no portão `spec`. `reject` vale nos dois. Reação como forma de confirmar (também citada na seção 5.2) não foi implementada.
- Lembrete por timer em cada espera (comentário idempotente `lembrete-N`); depois dos lembretes o workflow continua esperando (pausado).
- Depois de confirmar o intent e depois de aprovar a spec, o workflow relê `intent.md` e `spec.md` da branch (um humano pode ter editado) e usa essa versão. A leitura falha fechada: só 404 é ausência (e usa a versão do modelo); qualquer outro erro do GitHub é erro com retentativa e, esgotada, derruba a entrega; arquivo acima de 200 000 caracteres é recusado. Em dry-run não há branch e vale a versão do modelo.
- Commits: o assunto é saneado em uma linha e cada linha do corpo individualmente, para os trailers (`Intent-Id`, `Run-Id`, `Co-Authored-By`) continuarem trailers.
- Rejeição: o workflow publica o encerramento e termina com `Desfecho.REJEITADA`; a `Entrega` permanece no estado em que estava (AguardandoSpec). Não foi criada aresta em `TRANSICOES`.

## Decisão pendente do autor

Pendentes do autor: (1) o que a rejeição significa para a máquina de estados: (a) encerrar a entrega (implementado, sem mudar o núcleo); (b) voltar ao Design com o motivo, para uma nova spec; (c) voltar ao Build, no portão final. Recomendação: (b) para o portão de spec e (c) para o de aprovação, cada um como aresta e comando nomeados, com testes de propriedade, depois de o autor aprovar.

## Consequências

- Um humano que errou o comando não consegue reabrir a entrega; precisa de uma nova issue.
- Aprovação não registra "quem aprovou" no agregado (`Entrega.aprovar` só existe para o portão final, M4).

## Custo

Tokens e custo de cada sessão chegam ao `EtapaSaida`, às métricas `forja_custo_usd_total` e `forja_tokens_total` e ao `DeliverySaida.custo_usd`. O teto por entrega (`per_intent_usd` do policy.yaml) é do M5: até lá há medição, não bloqueio.
