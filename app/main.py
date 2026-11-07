# SPDX-FileCopyrightText: 2026 Anderson H. R. Ferreira
# SPDX-License-Identifier: MIT
"""API FastAPI: detecção de pessoas em zona de risco (JSON e PNG anotado)."""
from __future__ import annotations

import io
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import ValidationError

from . import __version__
from .config import Settings, get_settings
from .detector import DetectionResult, PersonDetector
from .geometry import to_pixels
from .render import render_annotated_png
from .risk import PersonRisk, classify_person, margin_in_pixels, overall_level
from .schemas import (
    Alert,
    BoundingBox,
    DetectResponse,
    HealthResponse,
    Metadata,
    PersonOut,
    RiskLevel,
    Summary,
    TimingsOut,
    ZoneConfig,
)

logger = logging.getLogger("edge_risk_zone")
STATIC_DIR = Path(__file__).resolve().parent / "static"
# A demonstração só fala com a própria origem: nada de CDN, fonte remota ou script externo.
DEMO_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; "
            "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
ALERT_MESSAGES: dict[RiskLevel, str] = {
    "green": "Nenhuma pessoa na zona de risco.",
    "yellow": "Atenção: pessoa próxima da zona de risco.",
    "red": "ALERTA: pessoa dentro da zona de risco.",
}


@dataclass
class Analysis:
    """Tudo o que uma análise produz. `/detect` e `/detect/image` só diferem na forma de responder.

    Guarda a imagem, o resultado do detector, o risco de cada pessoa e o geral, a zona usada (normalizada e
    em pixels), a margem em pixels e o limiar efetivo.
    """

    image: Image.Image
    result: DetectionResult
    risks: list[PersonRisk]
    level: RiskLevel
    zone: ZoneConfig
    polygon_px: list[tuple[float, float]]
    margin_px: float
    conf: float


def load_zone(path) -> ZoneConfig:
    """Lê a zona padrão de um arquivo JSON e valida."""
    with open(path, encoding="utf-8") as handle:
        return ZoneConfig(**json.load(handle))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Prepara o serviço uma única vez, na subida, antes de aceitar requisições.

    Carrega o modelo e a zona padrão, aplica o limite de pixels do Pillow e faz uma inferência de aquecimento.
    Tudo fica em `app.state`, compartilhado por todas as requisições.
    """
    settings: Settings = get_settings()
    app.state.settings = settings
    app.state.detector = PersonDetector(
        settings.model_path, settings.input_size, settings.intra_op_threads,
        settings.conf_threshold, settings.nms_iou, settings.max_concurrent_inferences)
    Image.MAX_IMAGE_PIXELS = settings.max_image_pixels  # o Pillow recusa o dobro disso (DecompressionBombError)
    app.state.default_zone = load_zone(settings.zone_path)
    # aquecimento: a primeira inferência costuma ser mais lenta (alocação e cache)
    app.state.detector.detect(Image.new("RGB", (settings.input_size, settings.input_size)))
    logger.info("Modelo %s carregado", app.state.detector.model_name)
    yield


app = FastAPI(
    title="Edge Risk Zone",
    version=__version__,
    description=("Detecta pessoas com YOLOX-Tiny (ONNX Runtime, CPU) e classifica o risco em relação a uma "
                 "zona poligonal. Protótipo educacional: não substitui sistemas de segurança certificados."),
    lifespan=lifespan,
)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    """Recusa corpos grandes e impede cache obsoleto dos arquivos da demonstração."""
    limit = request.app.state.settings.max_upload_bytes + 64 * 1024  # folga para o multipart
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        return JSONResponse({"detail": f"Corpo da requisição maior que {request.app.state.settings.max_upload_mb} MB"},
                            status_code=413)
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def _read_image(upload: UploadFile, settings: Settings) -> Image.Image:
    """Lê o upload e devolve a imagem em RGB, ou recusa com o código HTTP certo.

    - 413: arquivo acima do limite de bytes, ou resolução acima do limite de pixels (proteção contra
      "bombas de descompressão": poucos bytes que viram uma imagem enorme na memória);
    - 400: arquivo vazio ou que não é uma imagem.

    Lê no máximo `max_upload_bytes + 1` bytes: o byte a mais basta para saber que passou do limite sem carregar
    um arquivo gigante. A primeira abertura (`probe`) só lê o cabeçalho, para conferir a resolução antes de
    decodificar os pixels; `exif_transpose` aplica a rotação gravada pela câmera, para o detector ver a cena
    na orientação em que ela foi vista.
    """
    data = upload.file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"Arquivo maior que {settings.max_upload_mb} MB")
    if not data:
        raise HTTPException(400, "Arquivo vazio")
    try:
        probe = Image.open(io.BytesIO(data))
        if probe.width * probe.height > settings.max_image_pixels:
            raise HTTPException(413, "Imagem com resolução acima do limite")
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        return image.convert("RGB")
    except Image.DecompressionBombError as exc:
        raise HTTPException(413, "Imagem com resolução acima do limite") from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(400, "O arquivo enviado não é uma imagem válida") from exc


def _parse_zone(raw: str | None, default: ZoneConfig) -> ZoneConfig:
    """Devolve a zona do campo `zone` (JSON) ou, se ele faltar ou vier vazio, a zona padrão.

    Responde 422, com mensagem em português, quando o texto não é JSON, não tem a forma esperada
    (`polygon` e, opcionalmente, `margin`) ou o `ZoneConfig` recusa os valores.
    """
    if raw is None or not raw.strip():
        return default
    try:
        return ZoneConfig(**json.loads(raw))
    except (json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(422, "Campo 'zone' deve ser um JSON com 'polygon' e opcionalmente 'margin'") from exc
    except ValidationError as exc:
        message = "; ".join(err["msg"] for err in exc.errors())
        raise HTTPException(422, f"Zona inválida: {message}") from exc


def _analyze(request: Request, upload: UploadFile, zone_raw: str | None, conf: float | None) -> Analysis:
    """Fluxo compartilhado por `POST /detect` e `POST /detect/image`.

    Valida `conf` (entre 0 e 1, exclusivos), lê a imagem, escolhe a zona, detecta as pessoas, converte a zona de
    coordenadas normalizadas para pixels da imagem e classifica o risco de cada pessoa. Os endpoints só decidem
    como responder: JSON em `/detect`, PNG anotado em `/detect/image`.
    """
    state = request.app.state
    if conf is not None and not 0.0 < conf < 1.0:
        raise HTTPException(422, "O parâmetro 'conf' deve estar entre 0 e 1 (exclusive)")
    image = _read_image(upload, state.settings)
    zone = _parse_zone(zone_raw, state.default_zone)
    effective_conf = state.settings.conf_threshold if conf is None else conf
    result = state.detector.detect(image, effective_conf)
    polygon_px = to_pixels(zone.polygon, image.width, image.height)
    margin_px = margin_in_pixels(zone.margin, image.width, image.height)
    risks = [classify_person(d, polygon_px, margin_px) for d in result.detections]
    return Analysis(image, result, risks, overall_level(risks), zone, polygon_px, margin_px, effective_conf)


@app.get("/health", response_model=HealthResponse, tags=["serviço"])
def health(request: Request) -> HealthResponse:
    """Verificação de saúde, usada também pelo healthcheck do Docker."""
    detector: PersonDetector = request.app.state.detector
    return HealthResponse(status="ok", model=detector.model_name, input_size=detector.input_size,
                          providers=detector.session.get_providers(), version=__version__)


def _static_page(name: str) -> FileResponse:
    """Serve uma página HTML estática da demonstração, com a mesma CSP restritiva e sem cache."""
    return FileResponse(STATIC_DIR / name, media_type="text/html; charset=utf-8",
                        headers={"Content-Security-Policy": DEMO_CSP, "Cache-Control": "no-store",
                                 "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})


@app.get("/demo", include_in_schema=False)
def demo() -> FileResponse:
    """Página HTML de demonstração (offline): envia imagem, ajusta limiar e zona e mostra JSON e PNG anotado."""
    return _static_page("demo.html")


@app.get("/demo/ajuda", include_in_schema=False)
def demo_help() -> FileResponse:
    """Guia de uso da simulação, para os estudantes."""
    return _static_page("ajuda.html")


@app.get("/demo/pipeline", include_in_schema=False)
def demo_pipeline() -> FileResponse:
    """Mapa dos requisitos da Parte 1 do teste contra o que foi implementado, com a evidência de cada item."""
    return _static_page("pipeline.html")


@app.get("/zone", response_model=ZoneConfig, tags=["serviço"])
def default_zone(request: Request) -> ZoneConfig:
    """Zona de risco padrão carregada de `config/zone.json`."""
    return request.app.state.default_zone


@app.post("/detect", response_model=DetectResponse, tags=["inferência"])
def detect(
    request: Request,
    file: UploadFile = File(..., description="Imagem JPEG ou PNG"),
    zone: str | None = Form(None, description='JSON opcional: {"polygon": [[x, y], ...], "margin": 0.05}'),
    conf: float | None = Form(None, description="Limiar de confiança (padrão: variável CONF_THRESHOLD)"),
) -> DetectResponse:
    """Detecta pessoas e devolve JSON com caixas, confiança, distância à zona e nível de risco."""
    a = _analyze(request, file, zone, conf)
    persons = [
        PersonOut(
            id=i, confidence=round(r.detection.score, 4),
            bbox=BoundingBox(x1=round(r.detection.x1, 1), y1=round(r.detection.y1, 1),
                             x2=round(r.detection.x2, 1), y2=round(r.detection.y2, 1)),
            foot_point=(round(r.foot_point[0], 1), round(r.foot_point[1], 1)),
            distance_to_zone_px=round(r.distance_px, 1), risk_level=r.level)
        for i, r in enumerate(a.risks, start=1)
    ]
    counts = {lvl: sum(1 for r in a.risks if r.level == lvl) for lvl in ("green", "yellow", "red")}
    t = a.result.timings
    return DetectResponse(
        risk_level=a.level,
        alert=Alert(active=a.level != "green", level=a.level, message=ALERT_MESSAGES[a.level]),
        summary=Summary(persons_total=len(a.risks), **counts),
        persons=persons,
        metadata=Metadata(
            model=request.app.state.detector.model_name, input_size=request.app.state.detector.input_size,
            image_width=a.image.width, image_height=a.image.height, conf_threshold=a.conf,
            margin_px=round(a.margin_px, 1), zone=a.zone,
            timings=TimingsOut(preprocess_ms=round(t.preprocess_ms, 2), inference_ms=round(t.inference_ms, 2),
                               postprocess_ms=round(t.postprocess_ms, 2), total_ms=round(t.total_ms, 2))),
    )


@app.post("/detect/image", responses={200: {"content": {"image/png": {}}}}, tags=["inferência"])
def detect_image(
    request: Request,
    file: UploadFile = File(..., description="Imagem JPEG ou PNG"),
    zone: str | None = Form(None, description='JSON opcional: {"polygon": [[x, y], ...], "margin": 0.05}'),
    conf: float | None = Form(None, description="Limiar de confiança"),
) -> Response:
    """Devolve um PNG anotado com a zona, as caixas, os rótulos e o nível de risco."""
    a = _analyze(request, file, zone, conf)
    png = render_annotated_png(a.image, a.risks, a.polygon_px, a.margin_px, a.level)
    return Response(content=png, media_type="image/png", headers={
        "X-Risk-Level": a.level, "X-Persons": str(len(a.risks)),
        "X-Inference-Ms": f"{a.result.timings.inference_ms:.1f}"})
