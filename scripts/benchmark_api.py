#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Anderson H. R. Ferreira
# SPDX-License-Identifier: MIT
"""Mede a latência ponta a ponta da API em execução e a codificação do PNG anotado.

Uso: python scripts/benchmark_api.py --url http://127.0.0.1:18001 --container erz-bench \
     --json docs/benchmark_api_container.json
Requer httpx (requirements-dev.txt). Registra p50/p95/média de /detect e /detect/image,
a memória do container (docker stats) e o custo/tamanho do PNG em cada nível de compressão.

A latência inclui rede local, envio do arquivo (multipart), detecção e resposta, então é maior que a de
scripts/benchmark.py, que mede só o detector. Depende do hardware e da carga concorrente na máquina.
"""
from __future__ import annotations

import argparse
import io
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def pct(values: list[float], q: float) -> float:
    """Percentil pelo índice mais próximo, sem interpolação (mesmo método de scripts/benchmark.py)."""
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(q / 100 * (len(ordered) - 1))))]


def timed_requests(client: httpx.Client, url: str, image: bytes, warmup: int, runs: int) -> dict:
    """Envia `warmup` requisições descartadas e mede `runs` requisições, em milissegundos.

    Cada requisição reenvia a mesma imagem. O tempo inclui o envio, a detecção e o recebimento da resposta.
    """
    files = lambda: {"file": ("a.jpg", image, "image/jpeg")}  # noqa: E731
    for _ in range(warmup):
        client.post(url, files=files()).raise_for_status()
    samples, size = [], 0
    for _ in range(runs):
        t0 = time.perf_counter()
        response = client.post(url, files=files())
        samples.append((time.perf_counter() - t0) * 1000.0)
        response.raise_for_status()
        size = len(response.content)
    return {"p50_ms": round(pct(samples, 50), 1), "p95_ms": round(pct(samples, 95), 1),
            "mean_ms": round(statistics.fmean(samples), 1), "runs": runs, "response_bytes": size}


def png_levels(image_path: Path, repeats: int = 10) -> list[dict]:
    """Custo só de codificar o PNG em cada nível do zlib, no processo atual."""
    image = Image.open(image_path).convert("RGB")
    rows = []
    for level in (1, 3, 6, 9):
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", compress_level=level)
        t0 = time.perf_counter()
        for _ in range(repeats):
            io.BytesIO().write(b"")  # mantém o laço simétrico
            tmp = io.BytesIO()
            image.save(tmp, format="PNG", compress_level=level)
        rows.append({"compress_level": level, "encode_ms": round((time.perf_counter() - t0) / repeats * 1000, 1),
                     "bytes": len(buffer.getvalue())})
    return rows


def main() -> None:
    """Mede `/detect` e `/detect/image` no serviço em execução e imprime o resultado em JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--image", default="samples/airplane.jpg")
    parser.add_argument("--container", help="nome do container, para registrar a memória")
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--runs", type=int, default=60)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    image_bytes = (ROOT / args.image).read_bytes()
    with httpx.Client(timeout=60) as client:
        result = {"url": args.url, "image": args.image,
                  "detect": timed_requests(client, args.url + "/detect", image_bytes, args.warmup, args.runs),
                  "detect_image": timed_requests(client, args.url + "/detect/image", image_bytes,
                                                 args.warmup, args.runs),
                  "png_encoding_by_level": png_levels(ROOT / args.image)}
    if args.container:
        stats = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", args.container],
                               capture_output=True, text=True, check=False)
        result["container_memory"] = stats.stdout.strip()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
