# SPDX-FileCopyrightText: 2026 Anderson H. R. Ferreira
# SPDX-License-Identifier: MIT
"""Regra de risco: níveis por distância, margem inclusiva, ponto do pé e nível geral da cena."""
from app.detector import Detection
from app.risk import classify_person, margin_in_pixels, overall_level

ZONE = [(100.0, 100.0), (200.0, 100.0), (200.0, 200.0), (100.0, 200.0)]


def person(foot_x: float, foot_y: float) -> Detection:
    # caixa de 20x40 px cuja base está em (foot_x, foot_y)
    return Detection(foot_x - 10, foot_y - 40, foot_x + 10, foot_y, 0.9)


def test_levels_by_distance():
    assert classify_person(person(150, 150), ZONE, 30).level == "red"      # dentro
    assert classify_person(person(220, 150), ZONE, 30).level == "yellow"   # a 20 px da borda
    assert classify_person(person(300, 150), ZONE, 30).level == "green"


def test_margin_boundary_is_inclusive():
    assert classify_person(person(230, 150), ZONE, 30).level == "yellow"   # distância == margem
    assert classify_person(person(231, 150), ZONE, 30).level == "green"


def test_foot_point_is_bottom_center_not_box_center():
    # caixa que toca a zona só pela cabeça: o pé está fora, então não é vermelho
    tall = Detection(140, 20, 160, 90, 0.9)  # base em y=90, acima da zona (que começa em y=100)
    assert classify_person(tall, ZONE, 5).level == "green"


def test_overall_level_is_the_worst():
    risks = [classify_person(person(300, 150), ZONE, 30), classify_person(person(150, 150), ZONE, 30)]
    assert overall_level(risks) == "red"
    assert overall_level([]) == "green"


def test_margin_scales_with_image_diagonal():
    assert margin_in_pixels(0.05, 300, 400) == 25.0
