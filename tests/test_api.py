# SPDX-FileCopyrightText: 2026 Anderson H. R. Ferreira
# SPDX-License-Identifier: MIT
"""Contrato da API: `/health`, `/zone`, `/detect` e `/detect/image`, e os erros 400, 413 e 422."""
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app.main as main
from app.config import Settings

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "drill_press.jpg"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


def post_sample(client, endpoint="/detect", **data):
    with open(SAMPLE, "rb") as handle:
        return client.post(endpoint, files={"file": ("drill_press.jpg", handle, "image/jpeg")}, data=data)


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["providers"] == ["CPUExecutionProvider"]


def test_default_zone_endpoint(client):
    zone = client.get("/zone").json()
    assert len(zone["polygon"]) >= 3 and 0 <= zone["margin"] <= 0.5


def test_detect_returns_contract(client):
    response = post_sample(client)
    assert response.status_code == 200
    body = response.json()
    assert body["risk_level"] == "red" and body["alert"]["active"] is True
    assert body["summary"]["persons_total"] == len(body["persons"]) >= 5
    assert set(body["summary"]) == {"persons_total", "green", "yellow", "red"}
    person = body["persons"][0]
    assert {"id", "label", "confidence", "bbox", "foot_point", "distance_to_zone_px", "risk_level"} <= set(person)
    assert 0 < person["confidence"] <= 1 and person["label"] == "person"
    assert body["metadata"]["timings"]["inference_ms"] > 0
    assert body["metadata"]["image_width"] == 1280


def test_summary_counts_are_consistent(client):
    body = post_sample(client).json()
    summary = body["summary"]
    assert summary["green"] + summary["yellow"] + summary["red"] == summary["persons_total"]
    assert summary["red"] == sum(p["risk_level"] == "red" for p in body["persons"])


def test_detect_image_returns_png(client):
    response = post_sample(client, "/detect/image")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(PNG_SIGNATURE)
    assert response.headers["x-risk-level"] == "red"
    assert Image.open(io.BytesIO(response.content)).size == (1280, 1023)


def test_custom_zone_changes_levels(client):
    # zona minúscula no canto superior esquerdo: ninguém está nela nem perto dela
    zone = '{"polygon": [[0.0, 0.0], [0.05, 0.0], [0.05, 0.05]], "margin": 0.01}'
    body = post_sample(client, zone=zone).json()
    assert body["risk_level"] == "green" and body["alert"]["active"] is False
    assert body["metadata"]["zone"]["margin"] == 0.01


def test_high_confidence_threshold_reduces_detections(client):
    low = post_sample(client, conf="0.35").json()["summary"]["persons_total"]
    high = post_sample(client, conf="0.80").json()["summary"]["persons_total"]
    assert high < low


@pytest.mark.parametrize("zone", ['{"polygon": [[0, 0], [1, 1]]}', "not json", '{"polygon": [[0,0],[2,0],[1,1]]}'])
def test_invalid_zone_is_422(client, zone):
    assert post_sample(client, zone=zone).status_code == 422


@pytest.mark.parametrize("conf", ["0", "1", "-0.2", "1.5"])
def test_invalid_conf_is_422(client, conf):
    assert post_sample(client, conf=conf).status_code == 422


def test_non_image_is_400(client):
    response = client.post("/detect", files={"file": ("x.txt", b"isto nao e uma imagem", "text/plain")})
    assert response.status_code == 400


def test_empty_file_is_400(client):
    assert client.post("/detect", files={"file": ("x.jpg", b"", "image/jpeg")}).status_code == 400


def test_missing_file_is_422(client):
    assert client.post("/detect").status_code == 422


def test_oversize_upload_is_413(monkeypatch):
    monkeypatch.setattr(main, "get_settings", lambda: Settings(max_upload_mb=1))
    with TestClient(main.app) as small:
        big = b"\xff" * (1024 * 1024 + 10)
        assert small.post("/detect", files={"file": ("big.jpg", big, "image/jpeg")}).status_code == 413


def _png(width, height):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (128, 128, 128)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_image_above_pixel_limit_is_413(monkeypatch):
    monkeypatch.setattr(main, "get_settings", lambda: Settings(max_image_pixels=1000))
    with TestClient(main.app) as small:
        assert small.post("/detect", files={"file": ("a.png", _png(100, 100), "image/png")}).status_code == 413


def test_pillow_decompression_bomb_is_413_not_500(client, monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)  # o Pillow recusa acima do dobro (200 px)
    response = client.post("/detect", files={"file": ("a.png", _png(100, 100), "image/png")})
    assert response.status_code == 413


def test_declared_body_above_limit_is_rejected_before_reading(monkeypatch):
    monkeypatch.setattr(main, "get_settings", lambda: Settings(max_upload_mb=1))
    with TestClient(main.app) as small:
        response = small.post("/detect", files={"file": ("big.jpg", b"\xff" * (2 * 1024 * 1024), "image/jpeg")})
        assert response.status_code == 413
        assert "Corpo da requisição" in response.json()["detail"]
