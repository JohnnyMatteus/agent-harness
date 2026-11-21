# M1-10 · ACL do Claude Agent SDK e agente "eco"

- **core:** false
- **curso:** un-4.1
- **subagente:** implementador + testador
- **depende de:** M1-02, M1-09, ADRs 0003 e 0010
- **estimativa:** 1 dia

## Objetivo

Criar a porta `AgentRunner` e o adaptador sobre o `claude-agent-sdk`, traduzindo os tipos de mensagem do SDK para tipos do domínio, e um agente "eco" que roda dentro do sandbox, recebe o texto do Intent e devolve uma resposta simples, para provar o caminho completo sem lógica de negócio (seção 12, M1).

## Critérios de aceite

```gherkin
Funcionalidade: Agente eco

  Cenário: Resposta traduzida
    Dado um AgentRunner com SDK falso que emite mensagens do SDK
    Quando o eco roda
    Então o domínio recebe um RespostaDoAgente próprio, sem tipos do SDK

  Cenário: Dentro do sandbox
    Dado um sandbox ativo
    Quando o eco roda
    Então o diretório de trabalho do agente é o worktree do sandbox

  Cenário: Limites da sessão
    Dado um timeout e um teto de turnos configurados
    Quando o agente excede um deles
    Então a sessão é encerrada com erro explícito

  Cenário: Texto não confiável
    Dado um Intent cujo texto contém uma instrução de ignorar regras
    Quando o eco roda
    Então o texto vai ao contexto delimitado como dado e nenhuma ferramenta de escrita é concedida

  Cenário: Chamada direta
    Dado uma etapa de workflow simples
    Quando ela precisa classificar um texto
    Então usa o SDK anthropic direto, sem o loop de agente
```

## Arquivos prováveis

- `forja/application/portas/agente.py`
- `forja/infrastructure/agents/agent_sdk.py`, `forja/infrastructure/agents/eco.py`, `forja/infrastructure/agents/anthropic_direto.py`
- `tests/infrastructure/agents/test_eco.py`

## Notas

- Testes usam SDK falso; nenhuma chamada real ao modelo no CI.
- Prompts do eco ficam em arquivos versionados, não em strings no código.
