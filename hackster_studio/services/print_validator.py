"""Image checks for Lulu-ready full-bleed children's book art."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from sqlmodel import Session

from ..config import PRINT_DPI, PRINT_REQUIRED_PIXELS
from ..models import PrintReport


def _dpi_value(value: object) -> tuple[float, float]:
    if isinstance(value, tuple) and len(value) >= 2:
        return float(value[0]), float(value[1])
    return 0.0, 0.0


def validate_image_for_print(session: Session, image_path: str | Path) -> PrintReport:
    path = Path(image_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    with Image.open(path) as image:
        width_px, height_px = image.size
        dpi_x, dpi_y = _dpi_value(image.info.get("dpi"))

    size_ok = width_px >= PRINT_REQUIRED_PIXELS and height_px >= PRINT_REQUIRED_PIXELS
    dpi_ok = (dpi_x >= PRINT_DPI and dpi_y >= PRINT_DPI) if dpi_x and dpi_y else False
    pass_fail = size_ok and dpi_ok

    notes: list[str] = []
    if size_ok:
        notes.append("Pixel dimensions meet full-bleed 8.75 x 8.75 inch at 300 DPI requirement.")
    else:
        notes.append(f"Image is too small. Required at least {PRINT_REQUIRED_PIXELS} x {PRINT_REQUIRED_PIXELS}px.")
    if dpi_ok:
        notes.append("DPI metadata is at least 300 x 300.")
    else:
        notes.append("DPI metadata is missing or below 300 x 300.")

    report = PrintReport(
        file_path=str(path),
        width_px=width_px,
        height_px=height_px,
        dpi_x=dpi_x,
        dpi_y=dpi_y,
        required_width_px=PRINT_REQUIRED_PIXELS,
        required_height_px=PRINT_REQUIRED_PIXELS,
        pass_fail=pass_fail,
        notes=" ".join(notes),
    )
    session.add(report)
    session.commit()
    session.refresh(report)
    return report

