"""Transparent PNG text-art renderer for movable story-page lettering."""

from __future__ import annotations

import hashlib
import random
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


FONT_CANDIDATES = {
    "rounded": [
        "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf",
        "/System/Library/Fonts/SFNSRounded.ttf",
        "DejaVuSans-Bold.ttf",
    ],
    "storybook": [
        "/System/Library/Fonts/Supplemental/ChalkboardSE.ttc",
        "/System/Library/Fonts/Supplemental/Chalkboard.ttc",
        "DejaVuSans-Bold.ttf",
    ],
    "marker": [
        "/System/Library/Fonts/MarkerFelt.ttc",
        "/System/Library/Fonts/Supplemental/Chalkduster.ttf",
        "DejaVuSans-Bold.ttf",
    ],
    "comic": [
        "/System/Library/Fonts/Supplemental/Comic Sans MS Bold.ttf",
        "/System/Library/Fonts/Supplemental/Comic Sans MS.ttf",
        "DejaVuSans-Bold.ttf",
    ],
}


PROMPT_STYLE_PRESETS: list[tuple[tuple[str, ...], dict[str, Any]]] = [
    (("crystal", "sparkle", "magic", "glow"), {
        "fill_color": "#63DFFF",
        "stroke_color": "#F8FCFF",
        "shadow_color": "#2E8CFF",
        "shadow_opacity": 0.5,
        "effect": "sparkle",
        "font_family": "rounded",
        "stroke_width": 14,
    }),
    (("gold", "golden", "gear", "treasure", "adventure"), {
        "fill_color": "#F2C94C",
        "stroke_color": "#394A63",
        "shadow_color": "#8A6218",
        "shadow_opacity": 0.38,
        "effect": "sticker",
        "font_family": "storybook",
        "stroke_width": 16,
    }),
    (("robot", "cyber", "tech", "hackster", "electric"), {
        "fill_color": "#47C7FF",
        "stroke_color": "#394A63",
        "shadow_color": "#2E8CFF",
        "shadow_opacity": 0.42,
        "effect": "circuit",
        "font_family": "rounded",
        "stroke_width": 13,
    }),
    (("dragon", "green", "forest", "leaf"), {
        "fill_color": "#6BCB5B",
        "stroke_color": "#F8FCFF",
        "shadow_color": "#3FAF64",
        "shadow_opacity": 0.44,
        "effect": "sparkle",
        "font_family": "comic",
        "stroke_width": 12,
    }),
    (("marker", "hand", "handdrawn", "doodle"), {
        "fill_color": "#154C84",
        "stroke_color": "#F2C94C",
        "shadow_color": "#394A63",
        "shadow_opacity": 0.28,
        "effect": "doodle",
        "font_family": "marker",
        "stroke_width": 10,
    }),
]


def style_from_prompt(prompt: str | None) -> dict[str, Any]:
    """Map a freeform art-direction prompt to a deterministic typography preset."""
    normalized = (prompt or "").lower()
    if not normalized.strip():
        return {}

    style: dict[str, Any] = {}
    for keywords, preset in PROMPT_STYLE_PRESETS:
        if any(keyword in normalized for keyword in keywords):
            style.update(preset)

    if "bubble" in normalized or "comic" in normalized:
        style["font_family"] = "comic"
        style["stroke_width"] = max(int(style.get("stroke_width", 10)), 15)
    if "soft" in normalized or "gentle" in normalized:
        style["shadow_opacity"] = min(float(style.get("shadow_opacity", 0.34)), 0.22)
    if "bold" in normalized or "title" in normalized:
        style["stroke_width"] = max(int(style.get("stroke_width", 10)), 18)
    if "white" in normalized:
        style["stroke_color"] = "#F8FCFF"
    if "blue" in normalized:
        style["fill_color"] = "#47C7FF"
    if "yellow" in normalized:
        style["fill_color"] = "#F2C94C"

    return style


def _hex_to_rgba(value: str | None, alpha: int = 255) -> tuple[int, int, int, int]:
    raw = (value or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        return (21, 76, 132, alpha)
    try:
        return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16), alpha)
    except ValueError:
        return (21, 76, 132, alpha)


def _load_font(style: str, size_px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES.get(style, FONT_CANDIDATES["rounded"]):
        try:
            return ImageFont.truetype(candidate, size_px)
        except OSError:
            continue
    return ImageFont.load_default()


def _measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, stroke_width: int) -> tuple[int, int]:
    if not text:
        return (0, 0)
    bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=8, stroke_width=stroke_width)
    return (bbox[2] - bbox[0], bbox[3] - bbox[1])


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    stroke_width: int,
) -> str:
    lines: list[str] = []
    for raw_line in text.splitlines() or [""]:
        words = raw_line.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            if _measure(draw, trial, font, stroke_width)[0] <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return "\n".join(lines)


def _rng_for(text: str, style_prompt: str, variation_seed: int) -> random.Random:
    digest = hashlib.sha256(f"{text}|{style_prompt}|{variation_seed}".encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def _draw_star(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    radius: int,
    color: tuple[int, int, int, int],
) -> None:
    draw.line((x - radius, y, x + radius, y), fill=color, width=max(2, radius // 3))
    draw.line((x, y - radius, x, y + radius), fill=color, width=max(2, radius // 3))
    small = max(2, radius // 2)
    draw.line((x - small, y - small, x + small, y + small), fill=color, width=max(1, radius // 5))
    draw.line((x - small, y + small, x + small, y - small), fill=color, width=max(1, radius // 5))


def _draw_prompt_effects(
    draw: ImageDraw.ImageDraw,
    *,
    effect: str,
    rng: random.Random,
    width_px: int,
    height_px: int,
    accent: tuple[int, int, int, int],
) -> None:
    if effect == "sparkle":
        for _ in range(18):
            x = rng.randint(24, width_px - 24)
            y = rng.randint(18, height_px - 18)
            _draw_star(draw, x, y, rng.randint(5, 16), accent)
    elif effect == "circuit":
        for _ in range(10):
            x = rng.randint(30, width_px - 140)
            y = rng.randint(20, height_px - 20)
            length = rng.randint(36, 110)
            draw.line((x, y, x + length, y), fill=accent, width=3)
            draw.ellipse((x + length - 5, y - 5, x + length + 5, y + 5), fill=accent)
    elif effect == "doodle":
        for _ in range(8):
            x = rng.randint(24, width_px - 120)
            y = rng.randint(20, height_px - 40)
            draw.arc((x, y, x + rng.randint(36, 100), y + rng.randint(16, 44)), 10, 170, fill=accent, width=4)
    elif effect == "sticker":
        for _ in range(12):
            x = rng.randint(20, width_px - 20)
            y = rng.randint(18, height_px - 18)
            r = rng.randint(4, 10)
            draw.ellipse((x - r, y - r, x + r, y + r), fill=accent)


def render_text_art(
    text: str,
    output_path: Path,
    *,
    width_px: int = 1800,
    height_px: int = 520,
    dpi: int = 300,
    style: dict[str, Any] | None = None,
) -> Path:
    """Render exact editable dialogue as a transparent PNG text-art asset."""
    style = style or {}
    prompt = str(style.get("style_prompt", ""))
    style = {**style, **style_from_prompt(prompt)}
    output_path.parent.mkdir(parents=True, exist_ok=True)

    width_px = max(256, min(int(width_px), 4096))
    height_px = max(128, min(int(height_px), 2048))
    font_size = max(24, min(int(style.get("font_size_px", height_px * 0.28)), 420))
    stroke_width = max(0, min(int(style.get("stroke_width", font_size * 0.08)), 24))
    align = str(style.get("align", "center")).lower()
    if align not in {"left", "center", "right"}:
        align = "center"

    canvas = Image.new("RGBA", (width_px, height_px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    font = _load_font(str(style.get("font_family", "rounded")), font_size)
    padding = max(24, round(font_size * 0.35))
    max_text_width = max(32, width_px - (padding * 2))
    wrapped = _wrap_text(draw, text.strip(), font, max_text_width, stroke_width)

    shadow_alpha = max(0, min(int(float(style.get("shadow_opacity", 0.34)) * 255), 255))
    fill = _hex_to_rgba(style.get("fill_color", "#154C84"), 255)
    stroke = _hex_to_rgba(style.get("stroke_color", "#F2C94C"), 255)
    shadow = _hex_to_rgba(style.get("shadow_color", "#394A63"), shadow_alpha)
    shadow_dx = int(style.get("shadow_offset_x", max(3, font_size * 0.06)))
    shadow_dy = int(style.get("shadow_offset_y", max(5, font_size * 0.09)))
    effect = str(style.get("effect", "")).lower()
    variation_seed = int(style.get("variation_seed", 0))
    rng = _rng_for(text, prompt, variation_seed)
    accent = _hex_to_rgba(style.get("accent_color", style.get("stroke_color", "#F2C94C")), 150)
    line_spacing = max(6, round(font_size * 0.12))
    text_w, text_h = _measure(draw, wrapped, font, stroke_width)
    top = max(0, round((height_px - text_h) / 2))

    if align == "left":
        left = padding
    elif align == "right":
        left = max(padding, width_px - padding - text_w)
    else:
        left = round((width_px - text_w) / 2)

    _draw_prompt_effects(
        draw,
        effect=effect,
        rng=rng,
        width_px=width_px,
        height_px=height_px,
        accent=accent,
    )

    # Draw shadow first, then outlined fill for a playful, readable picture-book look.
    if shadow_alpha:
        draw.multiline_text(
            (left + shadow_dx, top + shadow_dy),
            wrapped,
            font=font,
            fill=shadow,
            spacing=line_spacing,
            align=align,
            stroke_width=stroke_width,
            stroke_fill=shadow,
        )
    draw.multiline_text(
        (left, top),
        wrapped,
        font=font,
        fill=fill,
        spacing=line_spacing,
        align=align,
        stroke_width=stroke_width,
        stroke_fill=stroke,
    )

    canvas.save(output_path, "PNG", dpi=(dpi, dpi))
    return output_path
