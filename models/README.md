# Modelo

| Campo | Valor |
|---|---|
| Arquivo | `yolox_tiny.onnx` (20.219.662 bytes) |
| Origem | https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_tiny.onnx |
| SHA-256 | `427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7` |
| Licença | Apache-2.0 (Megvii) |
| Entrada | `images`, `float32 [1, 3, 416, 416]`, BGR, valores 0 a 255, sem normalização |
| Saída | `output`, `float32 [1, 3549, 85]`: `cx, cy, w, h, objectness` + 80 classes COCO (cabeça bruta, sem NMS) |

O arquivo versionado evita baixar pesos na primeira requisição, o que quebraria
uma demonstração offline. Para conferir a integridade: `scripts/download_model.sh`.
