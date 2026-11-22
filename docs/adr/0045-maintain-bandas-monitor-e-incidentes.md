# 0045. Maintain: bandas, monitor e incidentes (parcial)

- **Status:** Proposto; implementação parcial (ver "Estado")
- **Data:** 2026-11-22
- **Id no design doc:** seção 10.2 e M6

## Decisão

- As bandas são do **operador**: um arquivo `<FORJA_BANDAS_DIR>/<dono>__<nome>.yaml` por repositório (subconjunto estrito de YAML, ADR 0042) vira `Bandas` com id, consulta PromQL (uma linha, até 1 000 caracteres), `max`, `for` (30s, 10m, 1h; até 24 h) e `on_breach` (só `diagnose_and_write_intent`). A consulta nunca vem do repositório monitorado, da issue ou do modelo; o nome do arquivo sai de um repositório validado (`dono/nome`), o arquivo precisa ser regular (symlink não vale) e ter até 64 KiB. A URL do Prometheus (`FORJA_PROMETHEUS_URL`) também é do operador: só http(s), sem credenciais, consulta ou fragmento, sem seguir redirecionamento; o adaptador só faz `GET /api/v1/query_range`.
- Cada verificação tem três resultados: `violada`, `dentro` e `sem_dados`. Falha fechada: série vazia, NaN ou infinito, série que não cobre a janela, com buracos ou desatualizada, resposta com `warnings`, série acima do teto de pontos (não é lida pela metade), várias séries, erro HTTP ou de rede, consulta que falha e arquivo de bandas ilegível viram `sem_dados` com o motivo, e `sem_dados` nunca é "tudo bem", nunca é "recuperado" e nunca abre incidente. Violada exige toda amostra da janela `for` acima do máximo. O monitor lista o que não conseguiu ver (`MonitorSaida.sem_dados`) e registra um aviso; ainda não há métrica nem alerta próprios para isso.
- `MonitorDeBandas` (Temporal) consulta as bandas em intervalos fixos, com `continue_as_new` periódico, e inicia um `IncidentWorkflow` filho com id determinístico por (repositório, banda, janela de 1 h): a mesma violação não abre dois incidentes.
- O diagnóstico é multiagente (ADR 0017): pesquisadores no RAG (documentos e ADRs) e nos deploys recentes alimentam um líder sem ferramenta (`tools=[]`, escrita negada); métricas, deploys e trechos chegam como dado delimitado e neutralizado, a evidência numérica é calculada por código, a saída é validada por schema e o líder só pode citar fontes que o RAG devolveu. O `incident.md` e o corpo da issue são renderizados por código, uma linha por item.
- A única ação externa é abrir uma issue com o label `forja:incident` (nunca `forja:intent`), uma vez por chave (idempotência atômica), neutralizada e em dry-run enquanto `FORJA_PUBLICAR` não for `true`. Um humano aplica `forja:intent` (portão), porque o fluxo ignora eventos de bot por desenho. Nenhuma ação corretiva (rollback, reinício, escala) é automática.
- Ligado por configuração explícita: sem `FORJA_MONITOR_REPOS` o monitor está desligado; ligado, exige `FORJA_PROMETHEUS_URL` e `FORJA_BANDAS_DIR` e só monitora repositório de `FORJA_REPOS_HABILITADOS`. O worker registra os workflows e as activities; `forja monitor` inicia (idempotente, id fixo por repositório) o monitor de cada repositório.

## Estado (o que falta)

- Nunca rodou contra um Prometheus ou GitHub reais (testes com dublês e `respx`); o modo Docker segue como no ADR 0036.
- O RAG de incidentes depende de os `incident.md` serem indexados como documento (o M2 não indexa incidentes); sem isso o diagnóstico cita só ADRs e documentos.
- Não há "recuperação" de incidente (fechar a issue ao voltar para `dentro`), reabertura nem métrica/alerta de `sem_dados`.
- O agendamento é o próprio workflow do monitor (timer + `continue_as_new`); `forja monitor` precisa ser executado uma vez após subir o worker (ou após limpar o namespace).
- O intervalo (`FORJA_MONITOR_INTERVALO_S`, 300 s) e a janela de deduplicação (1 h) são provisórios.
