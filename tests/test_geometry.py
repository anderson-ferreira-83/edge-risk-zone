# SPDX-FileCopyrightText: 2026 Anderson H. R. Ferreira
# SPDX-License-Identifier: MIT
"""Geometria da zona: ponto no polígono, distâncias, área, conversão para pixels e validação do polígono."""
import math

import pytest

from app.geometry import (distance_point_segment, distance_to_zone, point_in_polygon, polygon_area,
                          to_pixels, validate_polygon_norm)

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
# polígono em "L" (côncavo): o canto superior direito está vazio
L_SHAPE = [(0.0, 0.0), (10.0, 0.0), (10.0, 4.0), (4.0, 4.0), (4.0, 10.0), (0.0, 10.0)]


def test_point_inside_and_outside_square():
    assert point_in_polygon((5, 5), SQUARE)
    assert not point_in_polygon((11, 5), SQUARE)
    assert not point_in_polygon((-0.1, 5), SQUARE)


def test_concave_polygon_notch_is_outside():
    assert point_in_polygon((2, 8), L_SHAPE)       # braço vertical do L
    assert point_in_polygon((8, 2), L_SHAPE)       # braço horizontal do L
    assert not point_in_polygon((8, 8), L_SHAPE)   # o "vazio" do L


def test_distance_point_segment_projection_clamped():
    assert distance_point_segment((5, 3), (0, 0), (10, 0)) == pytest.approx(3.0)
    assert distance_point_segment((-3, 4), (0, 0), (10, 0)) == pytest.approx(5.0)  # antes do início
    assert distance_point_segment((13, 4), (0, 0), (10, 0)) == pytest.approx(5.0)  # depois do fim
    assert distance_point_segment((1, 1), (2, 2), (2, 2)) == pytest.approx(math.sqrt(2))  # segmento degenerado


def test_distance_to_zone_is_zero_inside_and_edge_distance_outside():
    assert distance_to_zone((5, 5), SQUARE) == 0.0
    assert distance_to_zone((13, 5), SQUARE) == pytest.approx(3.0)
    assert distance_to_zone((13, 14), SQUARE) == pytest.approx(5.0)  # distância ao vértice


def test_polygon_area_and_to_pixels():
    assert polygon_area(SQUARE) == pytest.approx(100.0)
    assert to_pixels([(0.5, 0.25)], 200, 100) == [(100.0, 25.0)]


@pytest.mark.parametrize("bad", [
    [[0, 0], [1, 1]],                       # só 2 vértices
    [[0, 0], [1, 0], [2, 1]],               # fora de [0, 1]
    [[0, 0], [0.5, 0.5], [1, 1]],           # colinear (área nula)
    [[0, 0], [1, 0], [1]],                  # vértice com 1 coordenada
    [[0, 0], [1, 0], [float("nan"), 1]],    # não finito
])
def test_validate_polygon_rejects_invalid(bad):
    with pytest.raises(ValueError):
        validate_polygon_norm(bad)


def test_validate_polygon_accepts_valid():
    assert validate_polygon_norm([[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]]) == [(0.1, 0.1), (0.9, 0.1), (0.5, 0.9)]
