#!/usr/bin/env bash
# Prepara o que o teste de integração do sandbox pressupõe: imagem, rede interna e proxy de saída.
# A rede dos sandboxes é --internal (sem rota externa); só o proxy também está na rede com saída.
# Falha se o proxy não subir e aceitar conexões na rede interna.
set -euo pipefail
cd "$(dirname "$0")"

docker build -t forja-sandbox:latest -f Dockerfile .
docker build -t forja-egress-proxy:latest -f Dockerfile.proxy .

docker network inspect forja-sandbox-net >/dev/null 2>&1 || docker network create --internal forja-sandbox-net
docker network inspect forja-egress-out >/dev/null 2>&1 || docker network create forja-egress-out

docker rm -f forja-egress-proxy >/dev/null 2>&1 || true
docker run -d --name forja-egress-proxy --network forja-egress-out forja-egress-proxy:latest
docker network connect forja-sandbox-net forja-egress-proxy

# `docker run -d` volta antes de o Squid subir (ou de ele morrer): espera a porta, da rede interna.
sonda='import socket,sys
try: socket.create_connection(("forja-egress-proxy",3128),timeout=2)
except OSError: sys.exit(1)'
for _ in $(seq 1 30); do
  if [ "$(docker inspect -f '{{.State.Running}}' forja-egress-proxy)" != "true" ]; then
    echo "proxy de saida terminou:" >&2
    docker logs --tail 40 forja-egress-proxy >&2 || true
    exit 1
  fi
  if docker run --rm --network forja-sandbox-net forja-sandbox:latest python -c "$sonda" 2>/dev/null; then
    echo "proxy de saida pronto"
    exit 0
  fi
  sleep 1
done
echo "proxy de saida nao aceitou conexoes em 30s:" >&2
docker logs --tail 40 forja-egress-proxy >&2 || true
exit 1
