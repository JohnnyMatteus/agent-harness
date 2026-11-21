# M1-09 · Sandbox efêmero por sessão: container, worktree e egress em allowlist

- **core:** false
- **curso:** fc4-tests-testcontainers
- **subagente:** implementador + devops + testador
- **depende de:** M1-01, ADRs 0008 e 0016
- **estimativa:** 1 dia

## Objetivo

Implementar a porta `Sandbox` com Docker rootless e `git worktree`: um container efêmero por sessão, usuário sem root, sistema de arquivos restrito ao worktree e saída de rede só para registries de pacotes e a API do modelo, via proxy de saída (seções 4.3 e 9.4).

## Critérios de aceite

```gherkin
Funcionalidade: Sandbox por sessão

  Cenário: Ciclo de vida
    Dado um repositório de teste
    Quando uma sessão pede um sandbox
    Então nasce um container com um worktree próprio
    E ao encerrar a sessão container e worktree são destruídos

  Cenário: Sem root
    Dado um sandbox ativo
    Quando um comando roda dentro dele
    Então o usuário não é root

  Cenário: Arquivos restritos
    Dado um sandbox ativo
    Quando um comando tenta ler ou escrever fora do worktree
    Então a operação falha

  Cenário: Rede em allowlist
    Dado um sandbox ativo
    Quando um comando acessa um host fora da allowlist
    Então a conexão é bloqueada e registrada
    E o acesso à API do modelo e a um registry de pacotes permitido funciona

  Cenário: Segredos fora do contexto
    Dado segredos de ambiente do host
    Quando um sandbox é criado
    Então nenhum segredo está no ambiente do container, salvo o injetado de propósito para um passo de teste
```

## Arquivos prováveis

- `forja/application/portas/sandbox.py`
- `forja/infrastructure/sandbox/docker.py`, `forja/infrastructure/sandbox/proxy_egress.py`, `forja/infrastructure/sandbox/worktree.py`
- `tests/infrastructure/sandbox/` (Testcontainers; marcados como integração)

## Notas

- Os ADRs 0008 e 0016 se sobrepõem; o autor pode fundi-los ao aceitar (ver `adr/README.md`).
- gVisor é opcional (seção 4.3) e fica fora do M1.
- O runtime de sandbox da Anthropic (bubblewrap + proxy) é a alternativa ao Docker rootless citada na seção 9.4; o M1 usa Docker rootless.
