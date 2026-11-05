# SPDX-FileCopyrightText: 2026 Anderson H. R. Ferreira
# SPDX-License-Identifier: MIT
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
        """Valida o polígono (mínimo de vértices, coordenadas entre 0 e 1); importa aqui para evitar ciclo de módulos."""
        from .geometry import validate_polygon_norm

        return validate_polygon_norm(value)


class BoundingBox(BaseModel):
    """Caixa delimitadora em pixels da imagem original: canto superior esquerdo (`x1`, `y1`) e inferior direito (`x2`, `y2`)."""

    x1: float
    y1: float
    x2: float
    y2: float


class PersonOut(BaseModel):
    """Uma pessoa detectada: caixa, confiança, ponto do pé, distância à zona e nível de risco."""

    id: int
    label: str = "person"
    confidence: float = Field(..., ge=0, le=1)
    bbox: BoundingBox
    foot_point: tuple[float, float] = Field(..., description="Centro da base da caixa, em pixels")
    distance_to_zone_px: float = Field(..., description="0 quando o ponto está dentro da zona")
    risk_level: RiskLevel


class Summary(BaseModel):
    """Quantas pessoas há em cada nível de risco, e o total."""

    persons_total: int
    green: int
    yellow: int
    red: int


class Alert(BaseModel):
    """Alerta da cena: `active` vale `true` para amarelo e vermelho; `level` é o pior nível entre as pessoas; `message` é um texto pronto para exibir."""

    active: bool
    level: RiskLevel
    message: str


class TimingsOut(BaseModel):
    """Tempos em milissegundos. `preprocess_ms` inclui a eventual espera pela vaga de inferência (veja `PersonDetector.detect`); `total_ms` é a soma das três etapas."""

    preprocess_ms: float
    inference_ms: float
    postprocess_ms: float
    total_ms: float


class Metadata(BaseModel):
    """Contexto da análise: modelo e tamanho de entrada, dimensões da imagem, limiar usado, margem em pixels, zona aplicada e tempos."""

    model: str
    input_size: int
    image_width: int
    image_height: int
    conf_threshold: float
    margin_px: float
    zone: ZoneConfig
    timings: TimingsOut


class DetectResponse(BaseModel):
    """Resposta de `POST /detect`: risco geral da cena, alerta, contagens, uma entrada por pessoa e metadados."""

    risk_level: RiskLevel
    alert: Alert
    summary: Summary
    persons: list[PersonOut]
    metadata: Metadata


class HealthResponse(BaseModel):
    """Estado do serviço: modelo carregado, tamanho de entrada, provedores do ONNX Runtime e versão."""

    status: Literal["ok"]
    model: str
    input_size: int
    providers: list[str]
    version: str
