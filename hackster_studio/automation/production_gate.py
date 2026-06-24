"""Production gate checks before running a full book image build."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .quality_checks import ImageValidationResult, parse_pixels, validate_image


@dataclass(frozen=True)
class ProductionGateResult:
    page_number: int
    page_path: Path
    image_path: Path
    pass_fail: bool
    page_exists: bool
    approved: bool
    image_validation: ImageValidationResult
    notes: list[str]


def evaluate_production_gate(
    *,
    book_root: Path,
    book: dict[str, Any],
    page_number: int = 1,
) -> ProductionGateResult:
    """Evaluate whether the approved pilot page is ready to unlock full production."""
    page_path = book_root / "pages" / f"page_{page_number:03d}.yaml"
    image_path = book_root / "illustrations" / f"page_{page_number:03d}.png"
    required_pixels = parse_pixels(book.get("required_pixels", "2625x2625"))
    validation = validate_image(page_number, image_path, required_pixels)
    notes: list[str] = []

    page_exists = page_path.exists()
    approved = False
    if page_exists:
        page = yaml.safe_load(page_path.read_text(encoding="utf-8")) or {}
        approved = page.get("approval_status") == "approved"
    else:
        notes.append(f"Pilot page YAML is missing: {page_path}")

    if not validation.pass_fail:
        notes.append("Pilot image must pass print-size validation.")
    if not approved:
        notes.append("Pilot page must be explicitly approved after visual QA.")
        notes.append(
            "Human QA must confirm no mouth marks, no text-like artifacts, no labels/patches/decals, "
            "clean Core Crystal, realistic storybook Niko design, child-safe tone, and no grid/tile artifacts."
        )

    pass_fail = page_exists and approved and validation.pass_fail
    if pass_fail:
        notes.append("Production gate passed: approved pilot page and print-valid image are present.")

    return ProductionGateResult(
        page_number=page_number,
        page_path=page_path,
        image_path=image_path,
        pass_fail=pass_fail,
        page_exists=page_exists,
        approved=approved,
        image_validation=validation,
        notes=notes,
    )


def write_production_gate_report(reports_dir: Path, result: ProductionGateResult) -> Path:
    """Write a Markdown report describing the current production gate state."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / "production_gate_report.md"
    validation = result.image_validation
    status = "PASS" if result.pass_fail else "FAIL"
    image_status = "PASS" if validation.pass_fail else "FAIL"
    notes = "\n".join(f"- {note}" for note in result.notes) if result.notes else "- None."
    validation_notes = "\n".join(f"- {note}" for note in validation.notes) if validation.notes else "- None."

    text = f"""# Production Gate Report

Result: {status}

## Pilot Page

- Page: {result.page_number:03d}
- Page YAML: `{result.page_path}`
- Page YAML exists: {result.page_exists}
- Approval status is approved: {result.approved}
- Image: `{result.image_path}`

## Image Validation

- Result: {image_status}
- Exists: {validation.exists}
- Readable: {validation.readable}
- Size: {validation.width_px}x{validation.height_px}
- DPI: {validation.dpi_x:g} x {validation.dpi_y:g}
- Square: {validation.is_square}
- Meets required resolution: {validation.meets_resolution}

## Gate Notes

{notes}

## Image Notes

{validation_notes}

## Human Visual QA Required Before Approval

- [ ] Niko has no mouth or mouth-like mark.
- [ ] Niko has the approved dimensional storybook look, not the simple flat-vector overlay style.
- [ ] Niko's helmet, face screen, antenna, hoodie, Core Crystal, backpack, limbs, and proportions match the approved reference.
- [ ] No text-like marks anywhere in the image.
- [ ] No hoodie, cuff, shoe, tool, or environment labels.
- [ ] Core Crystal is clean and non-symbolic.
- [ ] No gridlines, tile seams, halftone, or moire artifacts.
- [ ] Image is sharp enough for the 8.5 x 8.5 inch book.
- [ ] Composition leaves safe editable text space.
"""
    path.write_text(text, encoding="utf-8")
    return path
