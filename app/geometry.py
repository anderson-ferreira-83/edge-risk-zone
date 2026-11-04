"""Geometria 2D pura (sem dependências): polígono da zona e distâncias.

Todas as funções trabalham em pixels. A zona é guardada em coordenadas
normalizadas (0 a 1) e convertida para pixels pela função `to_pixels`,
o que a torna independente da resolução da câmera.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

Point = tuple[float, float]


def to_pixels(polygon_norm: Sequence[Point], width: int, height: int) -> list[Point]:
    """Converte um polígono normalizado (0 a 1) para pixels."""
    return [(x * width, y * height) for x, y in polygon_norm]


def polygon_area(polygon: Sequence[Point]) -> float:
    """Área pela fórmula do cadarço (shoelace); o valor é sempre positivo."""
    total = 0.0
    for i, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[(i + 1) % len(polygon)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def validate_polygon_norm(polygon: Sequence[Sequence[float]]) -> list[Point]:
    """Valida um polígono normalizado e o devolve como lista de tuplas.

    Regras: ao menos 3 vértices, cada um com 2 números finitos em [0, 1] e
    área não nula. Levanta ValueError com mensagem clara em caso contrário.
    """
    if len(polygon) < 3:
        raise ValueError("A zona precisa de pelo menos 3 vértices")
    points: list[Point] = []
    for vertex in polygon:
        if len(vertex) != 2:
            raise ValueError("Cada vértice deve ter exatamente 2 coordenadas [x, y]")
        x, y = float(vertex[0]), float(vertex[1])
        if not (math.isfinite(x) and math.isfinite(y)) or not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise ValueError("Coordenadas da zona devem estar normalizadas entre 0 e 1")
        points.append((x, y))
    if polygon_area(points) < 1e-6:
        raise ValueError("A zona tem área nula (vértices colineares)")
    return points


def point_in_polygon(point: Point, polygon: Sequence[Point]) -> bool:
    """Teste do raio (ray casting): conta quantas arestas um raio horizontal cruza."""
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        if (yi > y) != (yj > y):  # a aresta cruza a altura y
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def distance_point_segment(point: Point, a: Point, b: Point) -> float:
    """Menor distância de um ponto a um segmento (projeção limitada a [0, 1])."""
    px, py = point
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0.0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def distance_to_zone(point: Point, polygon: Sequence[Point]) -> float:
    """Distância do ponto à zona: 0 se estiver dentro, senão a menor distância às arestas."""
    if point_in_polygon(point, polygon):
        return 0.0
    return min(
        distance_point_segment(point, polygon[i], polygon[(i + 1) % len(polygon)])
        for i in range(len(polygon))
    )
