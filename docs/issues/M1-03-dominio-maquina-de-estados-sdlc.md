# M1-03 · Domínio: máquina de estados da Entrega (SDLC)

- **core:** true
- **curso:** fc4-ddd-events
- **subagente:** arquiteto + testador (tipos e testes falhando); implementação é do autor
- **depende de:** M1-02, ADR 0001
- **estimativa:** 1 dia

## Objetivo

Implementar o agregado `Entrega` com os estados e transições do diagrama da seção 5.1 (Plan, Design, AguardandoSpec, Build, Test, Review, AguardandoHumano, Deploy, Maintain) como código de domínio puro. É o item `maquina-de-estados-sdlc` do `plan.yaml`: modo par ligado, então o agente entrega tipos, testes falhando e o roteiro em `docs/roteiros/maquina-de-estados-sdlc.md`, e o autor escreve as regras de transição.

## Critérios de aceite

```gherkin
Funcionalidade: Máquina de estados da Entrega

  Cenário: Caminho feliz com raio baixo
    Dado uma Entrega em Plan com intent.md confirmado
    Quando ela avança por Design, Build, Test e Review com tudo verde e raio baixo
    Então chega a Deploy e depois a Maintain, emitindo SpecPronta, PlanoPronto, PRAberto e EntregaConcluida nos pontos corretos

  Cenário: Pontos em aberto na spec
    Dado uma Entrega em Design com spec.md com pontos em aberto
    Quando ela avança
    Então vai para AguardandoSpec e só segue para Build quando um humano resolve os pontos

  Cenário: Falha em teste volta ao Build
    Dado uma Entrega em Test
    Quando a verificação falha
    Então volta a Build e conta um ciclo
    E ao passar de N ciclos a transição é recusada com erro explícito

  Cenário: Raio alto exige humano
    Dado uma Entrega em Review com raio de impacto alto
    Quando ela avança
    Então vai para AguardandoHumano e só chega a Deploy com aprovação

  Cenário: Banda violada reinicia o ciclo
    Dado uma Entrega em Maintain
    Quando uma banda é violada
    Então nasce um novo intent.md e a próxima Entrega começa em Plan

  Cenário: Transição inválida
    Dado uma Entrega em Plan
    Quando alguém tenta ir direto para Deploy
    Então a transição é recusada e o estado não muda
```

## Arquivos prováveis

- `forja/domain/entrega.py`, `forja/domain/estados.py`
- `tests/domain/test_entrega.py` (inclui teste baseado em propriedades com hypothesis: nenhuma sequência de eventos chega a Deploy sem passar por Review)
- `docs/roteiros/maquina-de-estados-sdlc.md`

## Notas

- O valor de N (ciclos Test/Build) não está no design doc; precisa de decisão do autor.
- A classificação de raio de impacto vem de uma política (M5); no M1 ela entra como parâmetro da transição.
