"""Detector de pessoas: YOLOX-Tiny (COCO) executado com ONNX Runtime em CPU.

Pipeline em três etapas, cada uma cronometrada:
  1. pré-processamento: letterbox 416x416, ordem de canais BGR, float32 0-255;
  2. inferência: ONNX Runtime (CPUExecutionProvider);
  3. pós-processamento: decodifica a cabeça do YOLOX, filtra a classe
     "pessoa", aplica NMS e devolve as caixas na escala da imagem original.

NumPy e Pillow bastam: sem OpenCV, o que simplifica a imagem ARM64.
"""
from __future__ import annotations

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
        return self.preprocess_ms + self.inference_ms + self.postprocess_ms


@dataclass
class DetectionResult:
    detections: list[Detection] = field(default_factory=list)
    timings: Timings = field(default_factory=Timings)


def letterbox(image: Image.Image, size: int) -> tuple[np.ndarray, float]:
    """Redimensiona mantendo a proporção e preenche o resto com cinza.

    Como no YOLOX original, a imagem fica no canto superior esquerdo do
    quadrado. Devolve o tensor HWC (BGR, float32) e a razão de escala.
    """
    width, height = image.size
    ratio = min(size / height, size / width)
    new_w, new_h = int(round(width * ratio)), int(round(height * ratio))
    resized = np.asarray(image.resize((new_w, new_h), Image.Resampling.BILINEAR), dtype=np.float32)
    canvas = np.full((size, size, 3), PAD_VALUE, dtype=np.float32)
    canvas[:new_h, :new_w, :] = resized
    return canvas[:, :, ::-1], ratio  # RGB -> BGR, ordem usada no treino do modelo


def build_grids(size: int) -> tuple[np.ndarray, np.ndarray]:
    """Grades de células e strides para as três escalas da cabeça do YOLOX."""
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
    centers = (raw[:, 0:2] + grids) * strides
    sizes = np.exp(raw[:, 2:4]) * strides
    scores = raw[:, 4] * raw[:, 5 + PERSON_CLASS_ID]
    keep = scores >= conf_threshold
    centers, sizes, scores = centers[keep], sizes[keep], scores[keep]
    boxes = np.concatenate([centers - sizes / 2.0, centers + sizes / 2.0], axis=1)
    return boxes, scores


def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    """Non-Maximum Suppression: mantém a melhor caixa e descarta as muito sobrepostas."""
    if boxes.shape[0] == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)  # IoU = interseção / união
        order = order[1:][iou <= iou_threshold]
    return keep


class PersonDetector:
    """Carrega o modelo ONNX uma única vez e detecta pessoas em imagens PIL."""

    def __init__(self, model_path: Path, input_size: int = 416, intra_op_threads: int = 0,
                 conf_threshold: float = 0.35, nms_iou: float = 0.45) -> None:
        if not Path(model_path).is_file():
            raise FileNotFoundError(f"Modelo ONNX não encontrado: {model_path}")
        options = ort.SessionOptions()
        if intra_op_threads > 0:
            options.intra_op_num_threads = intra_op_threads
        self.session = ort.InferenceSession(str(model_path), options, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.input_size = input_size
        self.conf_threshold = conf_threshold
        self.nms_iou = nms_iou
        self.model_name = Path(model_path).name
        self._grids, self._strides = build_grids(input_size)

    def detect(self, image: Image.Image, conf_threshold: float | None = None) -> DetectionResult:
        """Executa o pipeline completo e devolve detecções e tempos."""
        conf = self.conf_threshold if conf_threshold is None else conf_threshold
        timings = Timings()

        t0 = time.perf_counter()
        padded, ratio = letterbox(image, self.input_size)
        blob = np.ascontiguousarray(padded.transpose(2, 0, 1)[None], dtype=np.float32)  # NCHW
        t1 = time.perf_counter()
        raw = self.session.run(None, {self.input_name: blob})[0][0]
        t2 = time.perf_counter()

        boxes, scores = decode_person_boxes(raw, self._grids, self._strides, conf)
        keep = nms(boxes, scores, self.nms_iou)
        width, height = image.size
        detections = []
        for i in keep:
            x1, y1, x2, y2 = (boxes[i] / ratio).tolist()  # volta à escala original
            detections.append(Detection(
                x1=max(0.0, x1), y1=max(0.0, y1), x2=min(float(width), x2), y2=min(float(height), y2),
                score=float(scores[i]),
            ))
        t3 = time.perf_counter()

        timings.preprocess_ms = (t1 - t0) * 1000.0
        timings.inference_ms = (t2 - t1) * 1000.0
        timings.postprocess_ms = (t3 - t2) * 1000.0
        return DetectionResult(detections=detections, timings=timings)
