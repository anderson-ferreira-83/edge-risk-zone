#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Anderson H. R. Ferreira
# SPDX-License-Identifier: MIT
# Teste de execução da imagem linux/arm64 EMULADA (QEMU) em um host x86_64.
# Pré-requisito (uma vez por boot; instala handlers binfmt no kernel, exige privilégio):
#   docker run --privileged --rm tonistiigi/binfmt --install arm64
# A emulação é MUITO mais lenta que a placa real: serve só para provar que a imagem sobe e
# responde. NÃO use os tempos medidos aqui como desempenho da Raspberry Pi 5.
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE="${1:-edge-risk-zone:multi}"   # gerada por scripts/build_multiarch.sh; o --platform abaixo escolhe a variante arm64
NAME="erz-arm64-smoke"
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --platform linux/arm64 -p 18002:8000 "$IMAGE" >/dev/null
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT
echo "Aguardando a API (a emulação pode levar 1 a 3 minutos)..."
for _ in $(seq 1 180); do curl -sf http://127.0.0.1:18002/health >/dev/null && break; sleep 2; done
echo "uname -m dentro do container: $(docker exec "$NAME" python -c 'import platform; print(platform.machine())')"
curl -s http://127.0.0.1:18002/health; echo
curl -s -X POST -F "file=@samples/drill_press.jpg" http://127.0.0.1:18002/detect \
  | python3 -c "import sys,json; j=json.load(sys.stdin); print('detect:', j['risk_level'], j['summary'], 'inferência (emulada):', j['metadata']['timings']['inference_ms'], 'ms')"
