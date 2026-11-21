# 0016. Sandbox com isolamento de arquivos e rede; autonomia total dentro dele, nada fora (F-16)

- **Status:** Proposto
- **Data:** 2026-11-21
- **Id no design doc:** F-16 (seção 13; detalhe nas seções 3A e 9.4)

## Contexto

Pedidos de permissão a cada comando destroem a autonomia; liberar comandos sem isolamento aumenta o risco. Isolar só arquivos ou só rede deixa caminho para exfiltração ou para persistência fora do worktree.

## Decisão

Dentro do sandbox, comandos rodam sem pedir aprovação; fora dele, nada roda. O isolamento de sistema de arquivos e de rede é aplicado junto. Implementação: runtime de sandbox da Anthropic (bubblewrap no Linux + proxy de rede) ou container rootless com proxy de saída por allowlist. Complementa o ADR 0008.

## Alternativas consideradas

- Isolar só arquivos ou só rede: descartado (seção 9.4).
- A escolha entre as duas implementações fica em aberto no design doc.

## Consequências

- Menos pedidos de aprovação por entrega, mais tentativas bloqueadas registradas (métricas da seção 3A).
- O autor precisa escolher a implementação antes do M1 (sandbox faz parte da fundação).
