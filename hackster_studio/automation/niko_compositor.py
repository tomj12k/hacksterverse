"""Composite locked Niko pose assets onto generated page backgrounds."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from .niko_lock import placement_for_page


def compose_niko_locked_pages(
    *,
    pages: list[dict[str, Any]],
    project_root: Path,
    book_root: Path,
    force: bool = False,
) -> dict[int, Path]:
    output_dir = book_root / "illustrations_locked"
    output_dir.mkdir(parents=True, exist_ok=True)
    composed: dict[int, Path] = {}
    for page in pages:
        page_number = int(page["page_number"])
        if page.get("niko_layer_mode") != "locked_overlay":
            continue
        background_path = Path(str(page.get("illustration_path", "")))
        if not background_path.exists():
            continue
        output_path = output_dir / f"page_{page_number:03d}.png"
        if output_path.exists() and not force:
            composed[page_number] = output_path
            continue
        compose_niko_locked_page(
            background_path=background_path,
            pose_path=project_root / "01_Characters" / "Niko" / "Poses" / f"niko_{page['niko_pose']}.png",
            output_path=output_path,
            page_number=page_number,
            force=force,
        )
        composed[page_number] = output_path
    return composed


def compose_niko_locked_page(
    *,
    background_path: Path,
    pose_path: Path,
    output_path: Path,
    page_number: int,
    force: bool = False,
) -> Path:
    if output_path.exists() and not force:
        return output_path
    placement = placement_for_page(page_number)
    if not placement:
        raise ValueError(f"No Niko placement configured for page {page_number:03d}.")
    if not pose_path.exists():
        raise FileNotFoundError(f"Niko pose asset not found: {pose_path}")

    with Image.open(background_path).convert("RGBA") as background:
        page_width, page_height = background.size
        target_height = max(1, int(page_height * placement.height))
        with Image.open(pose_path).convert("RGBA") as pose:
            target_width = max(1, int(pose.width * (target_height / pose.height)))
            pose_resized = pose.resize((target_width, target_height), Image.Resampling.LANCZOS)

        center_x = int(page_width * placement.center_x)
        base_y = int(page_height * placement.base_y)
        left = center_x - target_width // 2
        top = base_y - target_height

        composed = background.copy()
        composed.alpha_composite(pose_resized, (left, top))
        rgb = composed.convert("RGB")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rgb.save(output_path, dpi=(300, 300))
    return output_path


def locked_illustration_path(book_root: Path, page_number: int) -> Path:
    return book_root / "illustrations_locked" / f"page_{page_number:03d}.png"
