# 0015. Tool search, programmatic tool calling e code execution com MCP para reduzir tokens de ferramentas (F-15)

- **Status:** Proposto
- **Data:** 2026-11-21
- **Id no design doc:** F-15 (seção 13; detalhe nas seções 3A e 6.4)

## Contexto

Com vários servidores MCP (knowledge, github, repo, observability), carregar todas as definições em todo turno e trazer resultados intermediários grandes para o contexto custa muitos tokens.

## Decisão

As definições de ferramentas MCP têm carregamento sob demanda (tool search). Consultas em lote ao GitHub e à observabilidade são orquestradas por código: no sandbox, os servidores MCP também ficam expostos como API de código, e o agente escreve um script que chama várias ferramentas, filtra os dados e devolve só o resumo. Ferramentas com parâmetros complexos trazem de 1 a 5 exemplos de chamada correta. Respostas das ferramentas são enxutas, truncadas com indicação de "há mais", paginadas e com identificadores estáveis.

## Alternativas consideradas

- Carregar todas as ferramentas em todo turno: é a linha de base que a decisão quer reduzir (seção 6.4).

## Consequências

- Menos tokens de definição e de resultados intermediários, medidos antes e depois (M7).
- Code execution depende do sandbox (ADR 0016).
