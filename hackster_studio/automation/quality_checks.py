"""Quality and print-readiness checks for generated page art."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass(frozen=True)
class ImageValidationResult:
    page_number: int
    image_path: Path
    exists: bool
    readable: bool
    width_px: int
    height_px: int
    dpi_x: float
    dpi_y: float
    is_square: bool
    meets_resolution: bool
    pass_fail: bool
    notes: list[str]


def parse_pixels(value: str | int) -> tuple[int, int]:
    if isinstance(value, int):
        return value, value
    left, right = str(value).lower().replace(" ", "").split("x", 1)
    return int(left), int(right)


def _dpi_tuple(value: object) -> tuple[float, float]:
    if isinstance(value, tuple) and len(value) >= 2:
        return float(value[0]), float(value[1])
    return 0.0, 0.0


def validate_image(
    page_number: int,
    image_path: Path,
    required_pixels: tuple[int, int],
) -> ImageValidationResult:
    notes: list[str] = []
    if not image_path.exists():
        return ImageValidationResult(
            page_number=page_number,
            image_path=image_path,
            exists=False,
            readable=False,
            width_px=0,
            height_px=0,
            dpi_x=0,
            dpi_y=0,
            is_square=False,
            meets_resolution=False,
            pass_fail=False,
            notes=["Missing image file."],
        )

    try:
        with Image.open(image_path) as image:
            width_px, height_px = image.size
            dpi_x, dpi_y = _dpi_tuple(image.info.get("dpi"))
    except Exception as exc:
        return ImageValidationResult(
            page_number=page_number,
            image_path=image_path,
            exists=True,
            readable=False,
            width_px=0,
            height_px=0,
            dpi_x=0,
            dpi_y=0,
            is_square=False,
            meets_resolution=False,
            pass_fail=False,
            notes=[f"Image is not readable by Pillow: {exc}"],
        )

    required_width, required_height = required_pixels
    is_square = width_px == height_px
    meets_resolution = width_px >= required_width and height_px >= required_height
    if not is_square:
        notes.append("Image is not square.")
    if not meets_resolution:
        notes.append(f"Image is below required {required_width}x{required_height}px full-bleed size.")
    if dpi_x and dpi_y:
        notes.append(f"DPI metadata: {dpi_x:g} x {dpi_y:g}.")
    else:
        notes.append("DPI metadata not found.")
    if is_square and meets_resolution:
        notes.append("Image dimensions pass print-size checks.")

    return ImageValidationResult(
        page_number=page_number,
        image_path=image_path,
        exists=True,
        readable=True,
        width_px=width_px,
        height_px=height_px,
        dpi_x=dpi_x,
        dpi_y=dpi_y,
        is_square=is_square,
        meets_resolution=meets_resolution,
        pass_fail=is_square and meets_resolution,
        notes=notes,
    )


def page_review_checklist() -> list[str]:
    return [
        "Niko matches the approved realistic HN-01 storybook reference",
        "Niko does not use the simple flat-vector overlay style unless explicitly approved",
        "Niko has no tail, wings, animal ears, snout, paws, claws, fur, scales, or extra appendages",
        "no accidental text in image",
        "child-friendly",
        "correct characters",
        "correct scene",
        "hidden objects included",
        "enough empty space for text",
        "no scary imagery",
        "print resolution acceptable",
    ]
