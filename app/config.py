# SPDX-FileCopyrightText: 2026 Anderson H. R. Ferreira
# SPDX-License-Identifier: MIT
"""Configuração por variáveis de ambiente (12-factor), com padrões seguros."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_float(name: str, default: float) -> float:
    """Lê uma variável de ambiente como número decimal; se não for numérica, falha com mensagem clara."""
    try:
        return float(os.environ.get(name, default))
    except ValueError as exc:
        raise ValueError(f"Variável {name} deve ser numérica") from exc


def _env_int(name: str, default: int) -> int:
    """Lê uma variável de ambiente como inteiro; se não for inteira, falha com mensagem clara."""
    try:
        return int(os.environ.get(name, default))
    except ValueError as exc:
        raise ValueError(f"Variável {name} deve ser inteira") from exc


@dataclass(frozen=True)
class Settings:
    """Parâmetros do serviço. Todos têm variável de ambiente correspondente.

    Os valores padrão são lidos do ambiente quando este módulo é importado (são atributos da classe):
    mudar uma variável depois disso só tem efeito ao reiniciar o processo.
    """

    model_path: Path = Path(os.environ.get("MODEL_PATH", BASE_DIR / "models" / "yolox_tiny.onnx"))
    zone_path: Path = Path(os.environ.get("ZONE_PATH", BASE_DIR / "config" / "zone.json"))
    input_size: int = _env_int("INPUT_SIZE", 416)  # o modelo ONNX foi exportado em 416x416
    conf_threshold: float = _env_float("CONF_THRESHOLD", 0.35)
    nms_iou: float = _env_float("NMS_IOU", 0.45)
    intra_op_threads: int = _env_int("ORT_INTRA_THREADS", 0)  # 0 = padrão do ONNX Runtime
    max_concurrent_inferences: int = _env_int("MAX_CONCURRENT_INFERENCES", 1)  # evita disputar os núcleos da Pi
    max_upload_mb: int = _env_int("MAX_UPLOAD_MB", 10)
    max_image_pixels: int = _env_int("MAX_IMAGE_PIXELS", 40_000_000)

    @property
    def max_upload_bytes(self) -> int:
        """Limite do upload em bytes (`max_upload_mb` × 1 MiB)."""
        return self.max_upload_mb * 1024 * 1024


def get_settings() -> Settings:
    """Devolve as configurações do serviço, com os valores lidos do ambiente na importação do módulo."""
    return Settings()
