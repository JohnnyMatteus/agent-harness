# Roteiro: máquina de estados do SDLC (`maquina-de-estados-sdlc`)

Item núcleo (M1-03). Código em `forja/domain/{estados,entrega}.py`; testes em `tests/domain/test_entrega.py` e `tests/domain/test_entrega_propriedades.py`. Decisões: ADR 0001 (modelo), ADR 0031 (limite de ciclos).

## O problema

Uma intenção percorre Plan, Design, Build, Test, Review, Deploy e Maintain, com portões humanos. O estado precisa sobreviver a reinícios e a dias de espera (Temporal), e uma regra não pode ser contornada por um bug de chamada: ninguém chega a Deploy sem passar por Review, e nenhum caminho ignora o humano quando o raio de impacto é alto.

## A solução em uma página

1. **Um grafo, uma fonte de verdade.** `TRANSICOES: dict[Estado, frozenset[Estado]]` lista as arestas do diagrama da seção 5.1. Todo movimento passa por `Entrega._mover`, que recusa o que não está no grafo.
2. **Comandos nomeados, não "set estado".** `confirmar_intent`, `concluir_spec`, `concluir_build`, `registrar_verificacao`, `concluir_review`, `aprovar`, `concluir_deploy`. Cada um conhece o estado de origem e decide o destino a partir de fatos (pontos em aberto, verde/vermelho, raio, política).
3. **Recusa atômica.** Violação levanta `TransicaoInvalida` (ou `CiclosEsgotados`) antes de qualquer mutação: estado, contador e eventos ficam como estavam. Os testes de propriedade verificam isso para sequências arbitrárias.
4. **Eventos como saída.** O agregado acumula `SpecPronta`, `PlanoPronto`, `PRAberto`, `EntregaConcluida`, `BandaViolada`; quem persiste chama `retirar_eventos()`.
5. **Domínio puro.** Sem Temporal, sem GitHub. O workflow do M1-07 só traduz sinais e resultados de activities em comandos.

## Regras e suposições (o que o autor deve confirmar)

| Regra | Escolha atual | Por quê |
| --- | --- | --- |
| Pontos em aberto | `concluir_spec(n>0)` vai a AguardandoSpec; só `resolver_pontos_em_aberto` sai | portão humano antes do Build |
| Ciclos Test/Build | N configurável, padrão 3; a falha N+1 levanta `CiclosEsgotados` e fica em Test | ADR 0031; só Test->Build conta |
| Review com achados | volta ao Build sem contar ciclo e vale mesmo com raio alto | achado bloqueante vence o portão |
| Raio alto ou política nega | AguardandoHumano; `aprovar(quem)` exige nome (trailer `Approved-By`) | ADR 0006 |
| Rejeição humana | não existe aresta no diagrama; fica como ponto em aberto | o design doc não define |
| Banda violada | a Entrega fica em Maintain (terminal) e devolve uma nova Entrega em Plan | "nasce novo intent.md" |
| Pontos de emissão | SpecPronta ao entrar em Build; PlanoPronto no 1º Build->Test; PRAberto no 1º Test->Review; EntregaConcluida em Deploy->Maintain | o design doc não fixa; "uma vez só" evita duplicar em ciclos |

O raio de impacto é parâmetro (`RaioDeImpacto.BAIXO|ALTO`); a política de risco real é do M5.

## Como os testes provam as regras

- **Exemplos** (`test_entrega.py`): um teste por cenário Gherkin da issue, mais bordas (limite exato de ciclos, aprovador vazio, eventos únicos).
- **Propriedades** (`test_entrega_propriedades.py`, hypothesis):
  - qualquer sequência de comandos, válidos ou não, nunca visita Deploy sem ter visitado Review, nem Maintain sem Deploy;
  - toda mudança de estado é aresta de `TRANSICOES`, e comando recusado não altera estado, ciclos, aprovador nem eventos;
  - para todo par (origem, destino) o `_mover` aceita exatamente as arestas do grafo;
  - uma `RuleBasedStateMachine` explora sequências e confere invariantes após cada passo (ciclos dentro do limite).

## Alternativas

- **Biblioteca de FSM** (`transitions`, `python-statemachine`): menos código, mas as guardas dependem de parâmetros ricos e o grafo vira configuração dinâmica; aqui o grafo é uma tabela de 9 linhas e a regra fica legível e tipada.
- **Máquina de estados no próprio Temporal** (só código de workflow): acopla regra de negócio à orquestração e impede testar sem o servidor. O domínio puro roda em microssegundos e o workflow só o chama.
- **Event sourcing completo**: dá auditoria e replay, mas o git (`.forja/<id>/` e trailers) e o histórico do Temporal já são a trilha; custo alto sem necessidade no M1.
- **Um método genérico `avancar(evento)`**: menos métodos, mais ramos internos e erros só em runtime; comandos nomeados deixam o tipo da chamada documentar a intenção.

## Perguntas de entrevista

**Por que o limite de ciclos mora no agregado e não no workflow?** Porque é regra de negócio (quanto esforço tolerar) e precisa ser testável sem Temporal. O workflow decide o que fazer ao receber `CiclosEsgotados`.

**Como garantir que Deploy exige Review?** Pela estrutura: a única aresta que chega a Deploy sai de Review ou de AguardandoHumano, e esta só se alcança por Review. A propriedade com hypothesis testa isso contra sequências aleatórias, não só o caminho feliz.

**O que acontece se o worker cair no meio?** O agregado é reconstruído a partir do histórico durável do Temporal ou do repositório; os comandos são determinísticos e recusam repetições fora de ordem, então reprocessar não corrompe o estado.

**Por que `ciclos_usados >= max` recusa e não `>`?** Contamos voltas já feitas: com N=3, três falhas voltam, a quarta é recusada. Teste de borda cobre N=2.

**E se o humano rejeitar na aprovação?** Hoje não há aresta; é decisão em aberto (voltar ao Build com motivo, ou encerrar). Adicionar significa uma linha em `TRANSICOES`, um comando e testes; as propriedades continuam valendo.

**Como a banda violada reinicia o ciclo sem Maintain->Plan?** Maintain é terminal para a Entrega; o novo problema é uma nova Intent e uma nova Entrega, com outro id e histórico próprio. Evita estado reutilizado e contadores sujos.

**Por que levantar exceção em vez de retornar Result?** A violação é erro de quem chama (o workflow nunca deveria pedir); exceção de domínio tipada é explícita e não pode ser ignorada por esquecimento.
