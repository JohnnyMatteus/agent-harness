# M1-13 · Validação do critério de pronto do M1

- **core:** false
- **curso:** —
- **subagente:** revisor
- **depende de:** M1-03, M1-09, M1-12
- **estimativa:** meio dia

## Objetivo

Conferir, sem implementar nada novo, que o critério de pronto proposto no README foi atendido e registrar a evidência.

## Critérios de aceite

```gherkin
Funcionalidade: Validação do M1

  Cenário: Critério de pronto
    Dado todas as issues do M1 fechadas
    Quando eu rodo lint, tipos, testes unitários e o teste de integração do M1-12
    Então tudo passa

  Cenário: Núcleo do autor
    Dado a máquina de estados do M1-03
    Quando eu leio o roteiro e os testes
    Então todas as transições do diagrama da seção 5.1 estão cobertas e o autor aprovou o código

  Cenário: Segurança do sandbox
    Dado o sandbox do M1-09
    Quando eu rodo os testes de arquivos e de rede
    Então nada escapa do worktree nem da allowlist

  Cenário: ADRs
    Dado os ADRs usados no M1 (0001, 0003, 0004, 0007, 0008, 0010, 0016)
    Quando eu comparo com o código
    Então cada um está aceito pelo autor ou tem divergência registrada
```

## Arquivos prováveis

- `docs/validacao-m1.md`

## Notas

- Os itens de `plan.yaml` só mudam de status quando o `done_when` for comprovadamente atendido.
