# SPDX-FileCopyrightText: 2026 Anderson H. R. Ferreira
# SPDX-License-Identifier: MIT
"""Regra de risco: classifica cada pessoa em relação à zona de perigo.

Verde  : fora da zona e além da margem de atenção.
Amarelo: fora da zona, mas a menos de `margin` pixels da borda.
Vermelho: o ponto de contato com o piso está dentro da zona.

Importante: isto é detecção de PRESENÇA em uma região da imagem. Não é um
dispositivo de segurança certificado e não substitui barreiras físicas,
intertravamentos ou sistemas conformes à NR-12 / ISO 13849.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .detector import Detection
from .geometry import Point, distance_to_zone

LEVELS = ("green", "yellow", "red")


@dataclass(frozen=True)
class PersonRisk:
    detection: Detection
    foot_point: Point
    distance_px: float
    level: str


def margin_in_pixels(margin_fraction: float, width: int, height: int) -> float:
    """A margem é uma fração da diagonal da imagem, independente da resolução."""
    return margin_fraction * math.hypot(width, height)


def classify_person(detection: Detection, polygon_px: Sequence[Point], margin_px: float) -> PersonRisk:
    """Nível de risco de uma pessoa, a partir do ponto de contato com o piso (o pé).

    Usa-se o pé, e não a caixa inteira, porque a cabeça pode "tocar" a zona na imagem enquanto
    os pés estão longe dela. `distance_to_zone` devolve 0 para pontos dentro do polígono, por isso
    distância 0 é vermelho; até `margin_px` da borda (inclusive) é amarelo; além disso, verde.
    """
    foot = detection.foot_point
    distance = distance_to_zone(foot, polygon_px)
    if distance == 0.0:
        level = "red"
    elif distance <= margin_px:
        level = "yellow"
    else:
        level = "green"
    return PersonRisk(detection=detection, foot_point=foot, distance_px=distance, level=level)


def overall_level(risks: Sequence[PersonRisk]) -> str:
    """Nível geral da cena: o pior entre todas as pessoas."""
    if not risks:
        return "green"
    return max((r.level for r in risks), key=LEVELS.index)
