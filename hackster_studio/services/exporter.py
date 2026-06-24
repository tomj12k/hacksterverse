"""Server-side Pillow compositor — composes scene layers into a print-ready PNG."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from ..automation.comfyui_engine import set_dpi_metadata
from ..config import GENERATED_PAGES_DIR, PROJECT_ROOT, asset_serve_roots
from ..pathsafe import resolve_within


def _denorm(value: float, canvas_size: int) -> int:
    """Convert a 0–1 normalized value to pixels."""
    return round(value * canvas_size)


def _hex_to_rgb(value: str | None, default: tuple[int, int, int] = (30, 30, 30)) -> tuple[int, int, int]:
    raw = (value or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        return default
    try:
        return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
    except ValueError:
        return default


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines() or [""]:
        words = raw_line.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            bbox = draw.textbbox((0, 0), trial, font=font, stroke_width=2)
            if bbox[2] - bbox[0] <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _draw_draft_text_layer(canvas: Image.Image, layer: dict[str, Any]) -> None:
    W, H = canvas.size
    transform = layer.get("transform", {})
    scale = float(transform.get("scale", 1.0))
    opacity = max(0.0, min(1.0, float(transform.get("opacity", 1.0))))
    box_w = max(1, round(_denorm(transform.get("width", 0.8), W) * scale))
    box_h = max(1, round(_denorm(transform.get("height", 0.18), H) * scale))
    left = _denorm(transform.get("x", 0.5), W) - box_w // 2
    top = _denorm(transform.get("y", 0.75), H) - box_h // 2

    layer_canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer_canvas)
    box_alpha = round(max(0.0, min(1.0, float(layer.get("box_opacity", 0.88)))) * 255 * opacity)
    box_rgb = _hex_to_rgb(layer.get("box_color"), (255, 255, 255))
    radius = max(8, round(min(box_w, box_h) * 0.08))
    if box_alpha:
        draw.rounded_rectangle(
            (left, top, left + box_w, top + box_h),
            radius=radius,
            fill=(*box_rgb, box_alpha),
            outline=(57, 74, 99, round(70 * opacity)),
            width=max(1, round(H * 0.0015)),
        )

    font_size_px = max(12, _denorm(layer.get("font_size", 0.04), H))
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size_px)
    except OSError:
        font = ImageFont.load_default()

    pad = max(8, round(font_size_px * 0.55))
    lines = _wrap_text(draw, layer.get("text", ""), font, max(1, box_w - pad * 2))
    line_h = max(1, draw.textbbox((0, 0), "Ag", font=font, stroke_width=2)[3])
    spacing = max(4, round(font_size_px * 0.18))
    total_h = (line_h * len(lines)) + (spacing * max(0, len(lines) - 1))
    y = top + max(pad // 2, (box_h - total_h) // 2)
    align = layer.get("align", "center")
    fill = (*_hex_to_rgb(layer.get("text_color"), (21, 76, 132)), round(255 * opacity))
    stroke = (*_hex_to_rgb(layer.get("stroke_color"), (242, 201, 76)), round(230 * opacity))
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=2)
        line_w = bbox[2] - bbox[0]
        if align == "left":
            x = left + pad
        elif align == "right":
            x = left + box_w - pad - line_w
        else:
            x = left + (box_w - line_w) // 2
        draw.text((x, y), line, fill=fill, font=font, stroke_width=2, stroke_fill=stroke)
        y += line_h + spacing

    rotation = transform.get("rotation", 0)
    if rotation:
        # Draft text rotation is intentionally omitted for predictable page-box placement.
        pass
    canvas.alpha_composite(layer_canvas)


def _apply_shadow(img: Image.Image, shadow: dict[str, Any]) -> Image.Image:
    """Return img composited over its own directional drop shadow."""
    if not shadow.get("enabled"):
        return img

    angle_rad = math.radians(shadow.get("angle", 270))
    distance_px = shadow.get("distance", 12)
    blur_px = shadow.get("blur", 8)
    opacity = shadow.get("opacity", 0.3)

    offset_x = round(math.cos(angle_rad) * distance_px)
    offset_y = round(math.sin(angle_rad) * distance_px)

    img = img.convert("RGBA")
    alpha = img.split()[3]
    dark = Image.new("RGBA", img.size, (0, 0, 0, round(opacity * 255)))
    dark.putalpha(alpha)
    blurred = dark.filter(ImageFilter.GaussianBlur(radius=blur_px))

    shadow_canvas = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow_canvas.paste(blurred, (offset_x, offset_y), blurred)
    result = Image.alpha_composite(shadow_canvas, img)
    return result


def _composite_lighting(
    canvas: Image.Image,
    tint_hex: str,
    blend_mode: str,
    opacity: float,
) -> Image.Image:
    """Apply a tint overlay to canvas using multiply or screen blend."""
    r = int(tint_hex[1:3], 16)
    g = int(tint_hex[3:5], 16)
    b = int(tint_hex[5:7], 16)
    W, H = canvas.size
    tint_rgb = Image.new("RGB", (W, H), (r, g, b))
    canvas_rgb = canvas.convert("RGB")

    if blend_mode == "multiply":
        blended = ImageChops.multiply(canvas_rgb, tint_rgb)
    elif blend_mode == "screen":
        blended = ImageChops.screen(canvas_rgb, tint_rgb)
    else:
        blended = canvas_rgb

    result_rgb = Image.blend(canvas_rgb, blended, opacity)
    return result_rgb.convert("RGBA")


def export_scene(scene: dict[str, Any], mode: str = "flat") -> Path:
    """Composite all scene layers into a single print-ready PNG.

    :param scene: Parsed scene JSON dict.
    :param mode: 'flat' omits text layers (Affinity hand-off); 'draft' includes them.
    :returns: Path to the saved PNG file.
    """
    canvas_info = scene["canvas"]
    W: int = canvas_info["width_px"]
    H: int = canvas_info["height_px"]
    dpi: int = canvas_info["dpi"]

    canvas = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    layers = sorted(scene.get("layers", []), key=lambda lay: lay.get("z_index", 0))
    camera = next((lay for lay in layers if lay["type"] == "camera"), None)

    for layer in layers:
        layer_type = layer["type"]

        if layer_type == "camera":
            continue

        if layer_type == "text" and not layer.get("asset_path"):
            if mode == "flat":
                continue
            _draw_draft_text_layer(canvas, layer)
            continue

        if layer_type == "lighting":
            canvas = _composite_lighting(
                canvas,
                layer.get("tint_color", "#FFFFFF"),
                layer.get("blend_mode", "multiply"),
                layer.get("opacity", 0.0),
            )
            continue

        asset_path_str = layer.get("asset_path")
        if not asset_path_str:
            continue
        try:
            # asset_path comes from untrusted scene JSON; confine it to the
            # asset roots so a crafted layer cannot read arbitrary files.
            asset_file = resolve_within(PROJECT_ROOT / asset_path_str, asset_serve_roots(PROJECT_ROOT))
        except ValueError:
            continue
        if not asset_file.exists():
            continue

        img = Image.open(asset_file).convert("RGBA")

        transform = layer.get("transform", {})
        target_w = max(1, _denorm(transform.get("width", 1.0), W))
        target_h = max(1, _denorm(transform.get("height", 1.0), H))
        scale = transform.get("scale", 1.0)
        target_w = max(1, round(target_w * scale))
        target_h = max(1, round(target_h * scale))

        img = img.resize((target_w, target_h), Image.LANCZOS)

        rotation = transform.get("rotation", 0)
        if rotation:
            img = img.rotate(-rotation, expand=True, resample=Image.BICUBIC)

        if layer_type in ("character", "props"):
            img = _apply_shadow(img, layer.get("shadow", {}))

        opacity_val = float(transform.get("opacity", 1.0))
        if opacity_val < 1.0:
            r_ch, g_ch, b_ch, a_ch = img.split()
            a_ch = a_ch.point(lambda p: round(p * opacity_val))
            img = Image.merge("RGBA", (r_ch, g_ch, b_ch, a_ch))

        # Centered placement: x/y are center-point in normalized coords
        paste_x = _denorm(transform.get("x", 0.0), W) - img.width // 2
        paste_y = _denorm(transform.get("y", 0.0), H) - img.height // 2

        layer_canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        layer_canvas.paste(img, (paste_x, paste_y), img)
        canvas = Image.alpha_composite(canvas, layer_canvas)

    # Parallax offsets are preview-only; exporter applies camera crop to the flat composite.
    # Apply camera crop and zoom
    if camera:
        cam_t = camera.get("transform", {})
        zoom = float(cam_t.get("zoom", 1.0))
        crop_w = max(1, round(W / zoom))
        crop_h = max(1, round(H / zoom))
        cam_x = max(0, min(_denorm(cam_t.get("x", 0.0), W), W - crop_w))
        cam_y = max(0, min(_denorm(cam_t.get("y", 0.0), H), H - crop_h))
        canvas = canvas.crop((cam_x, cam_y, cam_x + crop_w, cam_y + crop_h))
        if zoom != 1.0:
            canvas = canvas.resize((W, H), Image.LANCZOS)

    book_slug = scene["book_slug"]
    page_number = scene["page_number"]
    out_dir = GENERATED_PAGES_DIR / book_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"page_{page_number:03d}_{mode}.png"

    canvas.convert("RGB").save(str(out_path), "PNG")
    set_dpi_metadata(out_path, dpi)
    return out_path
