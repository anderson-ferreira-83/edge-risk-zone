#!/usr/bin/env bash
# Baixa (se necessário) e confere o checksum do modelo YOLOX-Tiny ONNX.
set -euo pipefail
cd "$(dirname "$0")/.."
URL="https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_tiny.onnx"
SHA256="427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7"
FILE="models/yolox_tiny.onnx"
[ -f "$FILE" ] || curl -fL -o "$FILE" "$URL"
echo "$SHA256  $FILE" | sha256sum -c -
