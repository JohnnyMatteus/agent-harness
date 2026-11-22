#!/usr/bin/env bash
# Prepara o que o teste de integração do sandbox pressupõe: imagem, rede interna e proxy de saída.
# A rede dos sandboxes é --internal (sem rota externa); só o proxy também está na rede com saída.
set -euo pipefail
cd "$(dirname "$0")"

docker build -t forja-sandbox:latest -f Dockerfile .
docker build -t forja-egress-proxy:latest -f Dockerfile.proxy .

docker network inspect forja-sandbox-net >/dev/null 2>&1 || docker network create --internal forja-sandbox-net
docker network inspect forja-egress-out >/dev/null 2>&1 || docker network create forja-egress-out

docker rm -f forja-egress-proxy >/dev/null 2>&1 || true
docker run -d --name forja-egress-proxy --network forja-egress-out forja-egress-proxy:latest
docker network connect forja-sandbox-net forja-egress-proxy
