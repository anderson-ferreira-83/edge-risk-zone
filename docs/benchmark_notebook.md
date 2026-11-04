# Benchmark de latência (CPU, notebook)

**Isto NÃO é o desempenho da Raspberry Pi 5.** São medições de referência em um notebook x86_64,
limitadas a 4 núcleos para se parecerem com o número de núcleos da Pi. O Cortex-A76 da Pi 5 é
mais lento por núcleo, então espera-se latência maior. Veja "Como validar na placa" no README.

## Ambiente

| Item | Valor |
|---|---|
| CPU | AMD Ryzen 5 3600 6-Core Processor (processo fixado em 4 núcleos com `taskset -c 0-3`) |
| Arquitetura | x86_64 |
| Python / ONNX Runtime | 3.12.3 / 1.31.1 |
| Modelo | YOLOX-Tiny ONNX FP32, entrada 416x416 |
| Método | 10 execuções de aquecimento + 100 medidas por linha; tempos em ms |

Comando: `taskset -c 0-3 python scripts/benchmark.py --threads 1 2 4 --images samples/airplane.jpg samples/factory1910.jpg`

## Detector (pré-processamento + inferência + pós-processamento)

| imagem | threads | pessoas | pré p50 | inferência p50 | inferência p95 | pós p50 | total p50 | total p95 | FPS (p50) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| airplane.jpg | 1 | 6 | 5.55 | 61.33 | 72.14 | 0.38 | 67.34 | 78.95 | 14.9 |
| airplane.jpg | 2 | 6 | 6.53 | 40.35 | 51.23 | 0.43 | 47.49 | 60.42 | 21.1 |
| airplane.jpg | 4 | 6 | 6.27 | 27.82 | 33.67 | 0.44 | 34.67 | 41.47 | 28.8 |
| factory1910.jpg | 1 | 6 | 6.04 | 66.43 | 68.7 | 0.4 | 72.97 | 75.24 | 13.7 |
| factory1910.jpg | 2 | 6 | 6.09 | 36.81 | 48.22 | 0.4 | 43.39 | 54.58 | 23.0 |
| factory1910.jpg | 4 | 6 | 6.52 | 28.86 | 34.13 | 0.45 | 36.14 | 42.12 | 27.7 |

Leitura: a inferência domina o tempo (80% a 90% do total). Passar de 1 para 4 threads reduz a
latência total em cerca de 2x (não 4x, porque nem todo operador paraleliza). O pós-processamento
(decodificação e NMS) é desprezível, abaixo de 1 ms.

## Ponta a ponta pela API (container `amd64`, `--cpus 4`, `ORT_INTRA_THREADS=4`, imagem 1280x1023)

| Endpoint | p50 | p95 |
|---|---:|---:|
| `POST /detect` (JSON) | 52,4 ms | 70,4 ms |
| `POST /detect/image` (PNG anotado) | 172,1 ms | 192,9 ms |

Memória do container em repouso após as requisições: cerca de 127 MiB.

O PNG anotado custa mais do que a inferência. Com o nível de compressão padrão do zlib (6), o
endpoint levava 377 ms (p50); no nível 1 caiu para 172 ms com arquivo de tamanho quase igual
(1,39 MB contra 1,41 MB). O JSON não paga esse custo, e é o endpoint a usar em tempo real.
