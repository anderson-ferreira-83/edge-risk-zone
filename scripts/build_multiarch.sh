#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Anderson H. R. Ferreira
# SPDX-License-Identifier: MIT
# Gera a imagem para linux/amd64 e linux/arm64 com docker buildx, sem QEMU.
# Uso:
#   scripts/build_multiarch.sh                 # constrói e carrega localmente (armazenamento containerd)
#   scripts/build_multiarch.sh --push REGISTRY/NOME:TAG   # publica o manifesto multi-arquitetura
set -euo pipefail
cd "$(dirname "$0")/.."
TAG="edge-risk-zone:multi"
if [ "${1:-}" = "--push" ]; then
  TAG="${2:?informe REGISTRY/NOME:TAG}"
  docker buildx build --platform linux/amd64,linux/arm64 -t "$TAG" --push .
  docker buildx imagetools inspect "$TAG"
else
  docker buildx build --platform linux/amd64,linux/arm64 -t "$TAG" --load .
  for p in linux/amd64 linux/arm64; do
    echo "$p -> $(docker image inspect --platform "$p" "$TAG" --format '{{.Os}}/{{.Architecture}}')"
    python3 scripts/verify_arch.py "$TAG" "$p"
  done
fi
