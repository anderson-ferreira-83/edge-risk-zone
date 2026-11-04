"""Modelos Pydantic: contrato público das respostas JSON da API."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

RiskLevel = Literal["green", "yellow", "red"]


class ZoneConfig(BaseModel):
    """Zona de risco em coordenadas normalizadas (0 a 1) e margem de atenção."""

    polygon: list[tuple[float, float]] = Field(
        ..., description="Vértices [x, y] normalizados pela largura e altura da imagem")
    margin: float = Field(
        0.05, ge=0.0, le=0.5,
        description="Largura da faixa amarela, como fração da diagonal da imagem")

    @field_validator("polygon")
    @classmethod
    def _check_polygon(cls, value: list[tuple[float, float]]) -> list[tuple[float, float]]:
        from .geometry import validate_polygon_norm

        return validate_polygon_norm(value)


class BoundingBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float


class PersonOut(BaseModel):
    id: int
    label: str = "person"
    confidence: float = Field(..., ge=0, le=1)
    bbox: BoundingBox
    foot_point: tuple[float, float] = Field(..., description="Centro da base da caixa, em pixels")
    distance_to_zone_px: float = Field(..., description="0 quando o ponto está dentro da zona")
    risk_level: RiskLevel


class Summary(BaseModel):
    persons_total: int
    green: int
    yellow: int
    red: int


class Alert(BaseModel):
    active: bool
    level: RiskLevel
    message: str


class TimingsOut(BaseModel):
    preprocess_ms: float
    inference_ms: float
    postprocess_ms: float
    total_ms: float


class Metadata(BaseModel):
    model: str
    input_size: int
    image_width: int
    image_height: int
    conf_threshold: float
    margin_px: float
    zone: ZoneConfig
    timings: TimingsOut


class DetectResponse(BaseModel):
    risk_level: RiskLevel
    alert: Alert
    summary: Summary
    persons: list[PersonOut]
    metadata: Metadata


class HealthResponse(BaseModel):
    status: Literal["ok"]
    model: str
    input_size: int
    providers: list[str]
    version: str
