"""Transparent PNG cleanup for generated layer assets."""

from __future__ import annotations

from pathlib import Path
from statistics import median

import numpy as np
from PIL import Image, ImageChops, ImageDraw

_FILL = (255, 0, 255)  # sentinel used while flood-filling the background


def make_background_transparent(
    image_path: Path,
    *,
    tolerance: int = 26,
    feather: int = 28,
    dpi: int = 300,
) -> Path:
    """Convert a generated character image to an RGBA PNG with transparent background.

    ComfyUI/FLUX commonly returns RGB images even when asked for transparency.
    This removes the background by flood-filling inward from the image border,
    so only background pixels *connected to the edge* are made transparent. A
    character region that happens to match the background colour (e.g. a pale
    cream face on a near-white background) is preserved instead of being keyed
    out into a transparent — black-looking — hole.
    """
    with Image.open(image_path) as source:
        source_dpi = source.info.get("dpi", (dpi, dpi))
        rgba = source.convert("RGBA")
        # Recompute from RGB every time (do not early-return on existing alpha):
        # this also repairs files a previous global colour-key wrongly keyed.
        rgb = rgba.convert("RGB")
        background = _corner_background(rgb)

        # Soft per-pixel alpha from colour distance to the background, used only
        # at the background/character boundary so edges stay anti-aliased.
        diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, background)).convert("L")
        feathered = np.asarray(diff.point(lambda value: _alpha_for_difference(value, tolerance, feather)), dtype=np.uint8)

        bg_connected = _border_background_mask(rgb, background, tolerance)

        # Character pixels stay fully opaque; only edge-connected background gets
        # the feathered (mostly-zero) alpha.
        alpha_arr = np.where(bg_connected, feathered, np.uint8(255)).astype(np.uint8)
        rgba.putalpha(Image.fromarray(alpha_arr, mode="L"))
        rgba.save(image_path, format="PNG", dpi=source_dpi)
    return image_path


def _border_background_mask(rgb: Image.Image, background: tuple[int, int, int], tolerance: int) -> np.ndarray:
    """Boolean mask of background pixels reachable from the image border."""
    width, height = rgb.size
    flood = rgb.copy()
    px = flood.load()
    stride = max(1, min(width, height) // 64)
    seeds: list[tuple[int, int]] = []
    for x in range(0, width, stride):
        seeds.append((x, 0))
        seeds.append((x, height - 1))
    for y in range(0, height, stride):
        seeds.append((0, y))
        seeds.append((width - 1, y))

    for seed in seeds:
        if px[seed] == _FILL:
            continue  # already part of a flooded region
        pixel = rgb.getpixel(seed)
        # Only start a flood from border pixels that look like background.
        if sum(abs(a - b) for a, b in zip(pixel, background)) > tolerance * 3:
            continue
        ImageDraw.floodfill(flood, seed, _FILL, thresh=tolerance)

    flood_arr = np.asarray(flood)
    orig_arr = np.asarray(rgb)
    fill = np.array(_FILL, dtype=np.uint8)
    filled = np.all(flood_arr == fill, axis=2)
    was_fill = np.all(orig_arr == fill, axis=2)
    return filled & ~was_fill


def _corner_background(image: Image.Image) -> tuple[int, int, int]:
    width, height = image.size
    sample_size = max(4, min(24, width // 18, height // 18))
    boxes = [
        (0, 0, sample_size, sample_size),
        (width - sample_size, 0, width, sample_size),
        (0, height - sample_size, sample_size, height),
        (width - sample_size, height - sample_size, width, height),
    ]
    pixels: list[tuple[int, int, int]] = []
    for box in boxes:
        left, top, right, bottom = box
        for y in range(top, bottom):
            for x in range(left, right):
                pixels.append(image.getpixel((x, y)))
    return (
        int(median(pixel[0] for pixel in pixels)),
        int(median(pixel[1] for pixel in pixels)),
        int(median(pixel[2] for pixel in pixels)),
    )


def _alpha_for_difference(value: int, tolerance: int, feather: int) -> int:
    if value <= tolerance:
        return 0
    if value >= tolerance + feather:
        return 255
    return int(255 * ((value - tolerance) / max(1, feather)))
