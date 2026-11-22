# 0038. Portões humanos por sinal; rejeição encerra o workflow sem aresta nova na máquina de estados

- **Status:** Proposto, com decisão pendente do autor (ver abaixo)
- **Data:** 2026-11-22
- **Id no design doc:** seções 5.1, 5.2 (portões), 7 (comandos) e 7.1

## Contexto

O portão de spec (AguardandoSpec) e a confirmação do intent precisam de decisão humana durável. O design doc não define o que acontece quando o humano rejeita, e a máquina de estados é núcleo do autor.

## Decisão

- Comandos em comentário: `/forja confirm`, `/forja approve`, `/forja reject <motivo>` (além do `/forja stop` existente). O tradutor reconhece só linha inteira começando por `/forja` (citação com `>`, bot e menção no meio da frase não contam); o motivo é texto não confiável, limitado a 500 caracteres e neutralizado ao publicar.
- Só quem tem escrita no repositório sinaliza (mesma regra de ativação, seção 7). Cada comando vira um sinal do `DeliveryWorkflow`.
- `approve` e `reject` só valem com um portão aberto; um sinal que chega antes é descartado, não guardado, para uma aprovação antecipada não valer para um portão futuro. A confirmação do intent é guardada (o humano pode confirmar enquanto o Intérprete ainda roda).
- Lembrete por timer em cada espera (comentário idempotente `lembrete-N`); depois dos lembretes o workflow continua esperando (pausado).
- Aprovado o portão de spec, a versão de `spec.md` na branch (que um humano pode ter editado) substitui a gerada, e é ela que o Planner lê.
- Rejeição: o workflow publica o encerramento e termina com `Desfecho.REJEITADA`; a `Entrega` permanece no estado em que estava (AguardandoSpec). Não foi criada aresta em `TRANSICOES`.

## Decisão pendente do autor

O que a rejeição significa para a máquina de estados: (a) encerrar a entrega (implementado, sem mudar o núcleo); (b) voltar ao Design com o motivo, para uma nova spec; (c) voltar ao Build, no portão final. Recomendação: (b) para o portão de spec e (c) para o de aprovação, cada um como aresta e comando nomeados, com testes de propriedade, depois de o autor aprovar.

## Consequências

- Um humano que errou o comando não consegue reabrir a entrega; precisa de uma nova issue.
- Aprovação não registra "quem aprovou" no agregado (`Entrega.aprovar` só existe para o portão final, M4).
