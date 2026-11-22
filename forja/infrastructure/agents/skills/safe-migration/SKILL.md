---
name: safe-migration
description: Migrações reversíveis e em etapas, sem derrubar o serviço em produção.
---
# Migração segura

- Em etapas: adicionar (compatível), migrar dados, trocar o uso, só depois remover.
- Toda migração tem o caminho de volta testado. Nunca apagar coluna ou tabela na mesma entrega que para de usá-la.
- Migração é caminho de alto risco: exige humano.
