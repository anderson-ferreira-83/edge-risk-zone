"""Desenho da imagem anotada (PNG): zona, faixa de atenção, caixas e rótulos."""
from __future__ import annotations

import io
from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFont

from .geometry import Point
from .risk import PersonRisk

COLORS = {"green": (34, 160, 80), "yellow": (240, 190, 0), "red": (210, 40, 40)}
LABELS_PT = {"green": "VERDE", "yellow": "AMARELO", "red": "VERMELHO"}
# Nível 1 do zlib: codificar leva ~92 ms contra ~294 ms no nível padrão (6), com arquivo de tamanho parecido
# (docs/benchmark_api_container.json).
# Em CPU embarcada, a compressão do PNG pesa mais que a inferência do modelo.
PNG_COMPRESS_LEVEL = 1


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def render_annotated_png(
    image: Image.Image,
    risks: Sequence[PersonRisk],
    polygon_px: Sequence[Point],
    margin_px: float,
    level: str,
) -> bytes:
    """Desenha a cena e devolve os bytes de um PNG."""
    base = image.convert("RGBA")
    width, height = base.size
    scale = max(1.0, width / 640.0)  # espessuras e fontes proporcionais à imagem

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    band = max(1, int(2 * margin_px))
    closed = list(polygon_px) + [polygon_px[0]]
    yellow = COLORS["yellow"] + (70,)
    draw.line(closed, fill=yellow, width=band, joint="curve")
    radius = band / 2.0
    for x, y in polygon_px:  # arredonda os cantos da faixa
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=yellow)
    draw.polygon(list(polygon_px), fill=COLORS["red"] + (90,), outline=COLORS["red"] + (255,))
    canvas = Image.alpha_composite(base, overlay)

    draw = ImageDraw.Draw(canvas)
    font = _font(int(14 * scale))
    for index, risk in enumerate(risks, start=1):
        det, color = risk.detection, COLORS[risk.level]
        draw.rectangle([det.x1, det.y1, det.x2, det.y2], outline=color, width=max(2, int(2 * scale)))
        fx, fy = risk.foot_point
        r = 4 * scale
        draw.ellipse([fx - r, fy - r, fx + r, fy + r], fill=color, outline=(255, 255, 255))
        text = f"#{index} {det.score:.0%} {LABELS_PT[risk.level]}"
        left, top, right, bottom = draw.textbbox((det.x1, det.y1), text, font=font)
        label_h = bottom - top + 6
        y0 = det.y1 - label_h if det.y1 - label_h >= 0 else det.y1
        draw.rectangle([det.x1, y0, det.x1 + (right - left) + 8, y0 + label_h], fill=color)
        draw.text((det.x1 + 4, y0 + 2), text, fill=(0, 0, 0) if risk.level == "yellow" else (255, 255, 255), font=font)

    banner = f"RISCO GERAL: {LABELS_PT[level]} | pessoas: {len(risks)}"  # sem acento: a fonte padrão não tem todos os glifos
    banner_font = _font(int(18 * scale))
    left, top, right, bottom = draw.textbbox((0, 0), banner, font=banner_font)
    draw.rectangle([0, 0, right - left + 20, bottom - top + 14], fill=COLORS[level])
    draw.text((10, 5), banner, fill=(0, 0, 0) if level == "yellow" else (255, 255, 255), font=banner_font)

    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG", compress_level=PNG_COMPRESS_LEVEL)
    return buffer.getvalue()
