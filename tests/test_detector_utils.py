import numpy as np
from PIL import Image

from app.detector import build_grids, decode_person_boxes, letterbox, nms


def test_letterbox_shape_ratio_padding_and_bgr():
    image = Image.new("RGB", (200, 100), (255, 0, 0))  # vermelho puro em RGB
    padded, ratio = letterbox(image, 416)
    assert padded.shape == (416, 416, 3)
    assert ratio == 416 / 200
    assert padded[0, 0].tolist() == [0.0, 0.0, 255.0]      # BGR: o vermelho vai para o último canal
    assert padded[415, 415].tolist() == [114.0, 114.0, 114.0]  # área de preenchimento


def test_nms_keeps_best_and_drops_overlaps():
    boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], dtype=np.float32)
    scores = np.array([0.7, 0.9, 0.8], dtype=np.float32)
    assert nms(boxes, scores, 0.45) == [1, 2]
    assert nms(np.zeros((0, 4)), np.zeros(0), 0.45) == []


def test_nms_keeps_overlap_below_threshold():
    boxes = np.array([[0, 0, 10, 10], [8, 0, 18, 10]], dtype=np.float32)  # IoU = 20/180
    assert sorted(nms(boxes, np.array([0.9, 0.8]), 0.45)) == [0, 1]


def test_decode_places_box_from_cell_and_stride():
    grids, strides = build_grids(416)
    assert grids.shape == (3549, 2) and strides.shape == (3549, 1)
    raw = np.zeros((3549, 85), dtype=np.float32)
    # célula (x=10, y=20) da escala stride 8 é a linha 20*52 + 10
    row = 20 * 52 + 10
    raw[row, 0:2] = [0.5, 0.5]            # deslocamento dentro da célula
    raw[row, 2:4] = np.log([4.0, 8.0])    # largura 4*8=32, altura 8*8=64
    raw[row, 4] = 0.9                     # objectness
    raw[row, 5] = 0.8                     # classe 0 = pessoa
    boxes, scores = decode_person_boxes(raw, grids, strides, 0.35)
    assert boxes.shape == (1, 4)
    cx, cy = (10 + 0.5) * 8, (20 + 0.5) * 8
    np.testing.assert_allclose(boxes[0], [cx - 16, cy - 32, cx + 16, cy + 32], rtol=1e-5)
    assert scores[0] == np.float32(0.9) * np.float32(0.8)


def test_decode_ignores_other_classes_and_low_scores():
    grids, strides = build_grids(416)
    raw = np.zeros((3549, 85), dtype=np.float32)
    raw[0, 4], raw[0, 6] = 0.99, 0.99     # classe 1 (bicicleta), não pessoa
    raw[1, 4], raw[1, 5] = 0.3, 0.5       # pessoa, mas score 0.15 < limiar
    boxes, scores = decode_person_boxes(raw, grids, strides, 0.35)
    assert boxes.shape[0] == 0 and scores.shape[0] == 0
