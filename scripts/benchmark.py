#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Anderson H. R. Ferreira
# SPDX-License-Identifier: MIT
"""Mede a latência do detector em CPU: p50, p95 e média por etapa, após aquecimento.

Exemplos:
  python scripts/benchmark.py --threads 1 2 4
  taskset -c 0-3 python scripts/benchmark.py --threads 4      # limita a 4 núcleos (como a Raspberry Pi 5)

Os números valem para a MÁQUINA onde rodam. Na Raspberry Pi 5 o resultado será diferente,
então este script também deve ser executado na placa (veja a seção de validação no README).

Mede só o detector (pré-processamento, inferência e pós-processamento), sem HTTP nem PNG; a latência
ponta a ponta da API está em scripts/benchmark_api.py. Outros processos, ou requisições concorrentes
na mesma máquina, alteram o resultado: rode com o computador o mais ocioso possível.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
from pathlib import Path
from typing import Any

import onnxruntime as ort
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.detector import PersonDetector  # noqa: E402


def percentile(values: list[float], q: float) -> float:
    """Percentil pelo método do índice mais próximo, sem interpolação.

    Ordena as amostras e devolve a de posição `round(q/100 * (n-1))`. Com poucas amostras (cerca de 10),
    o p95 coincide com o máximo; por isso o padrão do script usa 100 execuções.
    """
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q / 100 * (len(ordered) - 1))))
    return ordered[index]


def cpu_model() -> str:
    """Nome da CPU; na Raspberry Pi o campo útil é "Model" ou "Hardware"."""
    try:
        lines = Path("/proc/cpuinfo").read_text().splitlines()
        for key in ("model name", "hardware", "model"):
            for line in lines:
                if line.lower().startswith(key) and ":" in line:
                    value = line.split(":", 1)[1].strip()
                    if not value.isdigit():
                        return value
    except OSError:
        pass
    return platform.processor() or platform.machine()


def run(image_path: Path, threads: int, warmup: int, runs: int) -> dict:
    """Mede `runs` execuções do detector com `threads` threads e resume cada etapa em p50, p95 e média.

    As `warmup` primeiras execuções são descartadas: a primeira inferência é mais lenta (alocação de memória
    e cache). Todas usam a mesma imagem, então a variação medida vem da máquina, não do conteúdo.
    """
    detector = PersonDetector(ROOT / "models" / "yolox_tiny.onnx", intra_op_threads=threads)
    image = Image.open(image_path).convert("RGB")
    for _ in range(warmup):
        detector.detect(image)
    stages: dict[str, list[float]] = {"preprocess_ms": [], "inference_ms": [], "postprocess_ms": [], "total_ms": []}
    persons = 0
    for _ in range(runs):
        result = detector.detect(image)
        persons = len(result.detections)
        for key in stages:
            stages[key].append(getattr(result.timings, key))
    summary: dict[str, Any] = {key: {"p50": round(percentile(v, 50), 2), "p95": round(percentile(v, 95), 2),
                     "mean": round(statistics.fmean(v), 2)} for key, v in stages.items()}
    summary.update(threads=threads, image=image_path.name, resolution=list(image.size),
                   persons=persons, fps_p50=round(1000 / summary["total_ms"]["p50"], 1))
    return summary


def main() -> None:
    """Roda cada combinação de imagem e número de threads e imprime uma tabela em Markdown.

    Com `--json`, salva também o ambiente (CPU, versões) e os resultados completos.
    """
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--threads", type=int, nargs="+", default=[0],
                        help="valores de intra_op_num_threads (0 = padrão)")
    parser.add_argument("--images", nargs="+", default=["samples/drill_press.jpg"])
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--runs", type=int, default=100)
    parser.add_argument("--json", type=Path, help="salva o resultado completo neste arquivo")
    args = parser.parse_args()

    env = {"cpu": cpu_model(), "cores_visible": len(os.sched_getaffinity(0)), "machine": platform.machine(),
           "python": platform.python_version(), "onnxruntime": ort.__version__,
           "warmup": args.warmup, "runs": args.runs}
    results = [run(ROOT / img, t, args.warmup, args.runs) for img in args.images for t in args.threads]

    print(f"CPU: {env['cpu']} | núcleos visíveis: {env['cores_visible']} | {env['machine']} | ORT {env['onnxruntime']}")
    print("| imagem | threads | pessoas | pré p50 | inferência p50 | inferência p95 | pós p50 | "
          "total p50 | total p95 | FPS (p50) |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in results:
        print(f"| {r['image']} | {r['threads'] or 'auto'} | {r['persons']} | {r['preprocess_ms']['p50']} | "
              f"{r['inference_ms']['p50']} | {r['inference_ms']['p95']} | {r['postprocess_ms']['p50']} | "
              f"{r['total_ms']['p50']} | {r['total_ms']['p95']} | {r['fps_p50']} |")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"environment": env, "results": results}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
