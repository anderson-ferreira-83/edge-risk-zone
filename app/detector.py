# SPDX-FileCopyrightText: 2026 Anderson H. R. Ferreira
# SPDX-License-Identifier: MIT
"""Detector de pessoas: YOLOX-Tiny (COCO) executado com ONNX Runtime em CPU.

Pipeline em três etapas, cada uma cronometrada:
  1. pré-processamento: letterbox 416x416, ordem de canais BGR, float32 0-255;
  2. inferência: ONNX Runtime (CPUExecutionProvider);
  3. pós-processamento: decodifica a cabeça do YOLOX, filtra a classe
     "pessoa", aplica NMS e devolve as caixas na escala da imagem original.

NumPy e Pillow bastam: sem OpenCV, o que simplifica a imagem ARM64.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image

PERSON_CLASS_ID = 0  # índice da classe "person" no COCO
PAD_VALUE = 114  # cinza usado pelo YOLOX no preenchimento do letterbox
STRIDES = (8, 16, 32)


@dataclass(frozen=True)
class Detection:
    """Uma pessoa detectada, com caixa em pixels da imagem original."""

    x1: float
    y1: float
    x2: float
    y2: float
    score: float

    @property
    def foot_point(self) -> tuple[float, float]:
        """Centro da base da caixa: aproxima o ponto de contato com o piso."""
        return ((self.x1 + self.x2) / 2.0, self.y2)


@dataclass
class Timings:
    """Tempos em milissegundos de cada etapa."""

    preprocess_ms: float = 0.0
    inference_ms: float = 0.0
    postprocess_ms: float = 0.0

    @property
    def total_ms(self) -> float:
        """Soma das três etapas, em milissegundos."""
        return self.preprocess_ms + self.inference_ms + self.postprocess_ms


@dataclass
class DetectionResult:
    detections: list[Detection] = field(default_factory=list)
    timings: Timings = field(default_factory=Timings)


def letterbox(image: Image.Image, size: int) -> tuple[np.ndarray, float]:
    """Redimensiona mantendo a proporção e preenche o resto com cinza.

    Como no YOLOX original, a imagem fica no canto superior esquerdo do
    quadrado. Devolve o tensor HWC (BGR, float32) e a razão de escala.

    Os valores ficam em 0-255: este modelo YOLOX espera pixels crus, sem dividir por 255
    nem subtrair média. A razão de escala serve para devolver as caixas à imagem original.
    """
    width, height = image.size
    ratio = min(size / height, size / width)
    new_w, new_h = int(round(width * ratio)), int(round(height * ratio))
    resized = np.asarray(image.resize((new_w, new_h), Image.Resampling.BILINEAR), dtype=np.float32)
    canvas = np.full((size, size, 3), PAD_VALUE, dtype=np.float32)
    canvas[:new_h, :new_w, :] = resized
    return canvas[:, :, ::-1], ratio  # RGB -> BGR, ordem usada no treino do modelo


def scale_and_clip(box: np.ndarray, ratio: float, width: int, height: int, score: float,
                   min_side: float = 1.0) -> Detection | None:
    """Volta a caixa à escala da imagem original e recorta cada coordenada aos limites.

    Devolve None quando a caixa fica sem área útil (por exemplo, quando estava inteira na
    região de preenchimento do letterbox), o que evita um retângulo invertido no desenho.
    """
    x1, y1, x2, y2 = (float(v) / ratio for v in box)
    x1, x2 = (min(max(v, 0.0), float(width)) for v in (x1, x2))
    y1, y2 = (min(max(v, 0.0), float(height)) for v in (y1, y2))
    if x2 - x1 < min_side or y2 - y1 < min_side:
        return None
    return Detection(x1=x1, y1=y1, x2=x2, y2=y2, score=float(score))


def build_grids(size: int) -> tuple[np.ndarray, np.ndarray]:
    """Grades de células e strides para as três escalas da cabeça do YOLOX.

    Cada célula vira um candidato a detecção. Para a entrada de 416 pixels são
    52x52 + 26x26 + 13x13 = 2704 + 676 + 169 = 3549 candidatos (strides 8, 16 e 32).
    """
    grids, strides = [], []
    for stride in STRIDES:
        cells = size // stride
        xv, yv = np.meshgrid(np.arange(cells), np.arange(cells))
        grid = np.stack((xv, yv), axis=2).reshape(-1, 2)
        grids.append(grid)
        strides.append(np.full((grid.shape[0], 1), stride))
    return np.concatenate(grids, axis=0).astype(np.float32), np.concatenate(strides, axis=0).astype(np.float32)


def decode_person_boxes(
    raw: np.ndarray, grids: np.ndarray, strides: np.ndarray, conf_threshold: float
) -> tuple[np.ndarray, np.ndarray]:
    """Converte a saída bruta (N, 85) em caixas xyxy e escores da classe pessoa.

    Cada linha é [cx, cy, w, h, objectness, 80 classes]. O centro é relativo
    à célula e a largura/altura estão em escala logarítmica.
    """
    # Célula + deslocamento previsto, multiplicado pelo stride, dá o centro em pixels da entrada.
    centers = (raw[:, 0:2] + grids) * strides
    # A rede prevê o logaritmo do tamanho: exp() desfaz e o stride converte para pixels.
    sizes = np.exp(raw[:, 2:4]) * strides
    # Escore = P(existe um objeto) x P(é uma pessoa); as outras 79 classes são ignoradas.
    scores = raw[:, 4] * raw[:, 5 + PERSON_CLASS_ID]
    # Filtra pelo limiar antes do NMS: dos 3549 candidatos sobram poucos e o NMS fica barato.
    keep = scores >= conf_threshold
    centers, sizes, scores = centers[keep], sizes[keep], scores[keep]
    # (cx, cy, w, h) -> (x1, y1, x2, y2)
    boxes = np.concatenate([centers - sizes / 2.0, centers + sizes / 2.0], axis=1)
    return boxes, scores


def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    """Non-Maximum Suppression: mantém a melhor caixa e descarta as muito sobrepostas."""
    if boxes.shape[0] == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]  # do maior escore para o menor
    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])  # a melhor caixa que sobrou é mantida
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)  # IoU = interseção / união
        order = order[1:][iou <= iou_threshold]  # IoU alto com a mantida = mesma pessoa: descarta
    return keep


class PersonDetector:
    """Carrega o modelo ONNX uma única vez e detecta pessoas em imagens PIL."""

    def __init__(self, model_path: Path, input_size: int = 416, intra_op_threads: int = 0,
                 conf_threshold: float = 0.35, nms_iou: float = 0.45, max_concurrent: int = 1) -> None:
        """Carrega o modelo ONNX uma vez e confere que a resolução pedida é a que ele exige (entrada fixa)."""
        if not Path(model_path).is_file():
            raise FileNotFoundError(f"Modelo ONNX não encontrado: {model_path}")
        options = ort.SessionOptions()
        if intra_op_threads > 0:
            options.intra_op_num_threads = intra_op_threads
        self.session = ort.InferenceSession(str(model_path), options, providers=["CPUExecutionProvider"])
        model_input = self.session.get_inputs()[0]
        self.input_name = model_input.name
        fixed = [d for d in model_input.shape[2:] if isinstance(d, int)]
        if fixed and any(d != input_size for d in fixed):
            raise ValueError(
                f"INPUT_SIZE={input_size}, mas o modelo exige entrada {model_input.shape}. "
                "Para outra resolução é preciso exportar outro ONNX.")
        # Limita as inferências simultâneas: várias ao mesmo tempo disputariam os núcleos da CPU
        # (na Raspberry Pi 5, 4) e piorariam a latência de todas.
        self._slots = threading.BoundedSemaphore(max(1, max_concurrent))
        self.input_size = input_size
        self.conf_threshold = conf_threshold
        self.nms_iou = nms_iou
        self.model_name = Path(model_path).name
        self._grids, self._strides = build_grids(input_size)

    def detect(self, image: Image.Image, conf_threshold: float | None = None) -> DetectionResult:
        """Executa o pipeline completo e devolve detecções e tempos."""
        conf = self.conf_threshold if conf_threshold is None else conf_threshold

        # 1) Pré-processamento
        t0 = time.perf_counter()
        padded, ratio = letterbox(image, self.input_size)
        blob = np.ascontiguousarray(padded.transpose(2, 0, 1)[None], dtype=np.float32)  # NCHW
        # 2) Inferência: uma por vez (semáforo)
        with self._slots:
            # t1 é registrado depois da aquisição: no contrato atual, uma eventual espera
            # pela vaga entra em preprocess_ms, não em inference_ms.
            t1 = time.perf_counter()
            raw = self.session.run(None, {self.input_name: blob})[0][0]
            t2 = time.perf_counter()

        # 3) Pós-processamento: decodifica, filtra a classe pessoa, aplica NMS e volta à escala original
        boxes, scores = decode_person_boxes(raw, self._grids, self._strides, conf)
        keep = nms(boxes, scores, self.nms_iou)
        width, height = image.size
        detections = [d for i in keep
                      if (d := scale_and_clip(boxes[i], ratio, width, height, scores[i])) is not None]
        t3 = time.perf_counter()

        timings = Timings(preprocess_ms=(t1 - t0) * 1000.0, inference_ms=(t2 - t1) * 1000.0,
                          postprocess_ms=(t3 - t2) * 1000.0)
        return DetectionResult(detections=detections, timings=timings)
