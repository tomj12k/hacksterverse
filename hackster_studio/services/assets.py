"""Asset library scanning — discovers available layer images by type."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from ..automation.niko_lock import NIKO_POSES
from ..config import GENERATED_PAGES_DIR, LAYERS_DIR, PROJECT_ROOT


def _relative_paths(directory: Path) -> list[str]:
    """Return PROJECT_ROOT-relative POSIX paths for all PNGs in directory."""
    if not directory.exists():
        return []
    return sorted(
        p.relative_to(PROJECT_ROOT).as_posix()
        for p in directory.rglob("*.png")
    )


def _relative_image_paths(directory: Path) -> list[str]:
    """Return PROJECT_ROOT-relative POSIX paths for common raster image files."""
    if not directory.exists():
        return []
    extensions = {".png", ".jpg", ".jpeg", ".webp"}
    return sorted(
        p.relative_to(PROJECT_ROOT).as_posix()
        for p in directory.rglob("*")
        if p.is_file() and p.suffix.lower() in extensions
    )


def list_assets() -> dict[str, Any]:
    """Scan assets/layers/ and return image paths grouped by layer type."""
    chars_dir = LAYERS_DIR / "characters"
    characters: dict[str, list[str]] = {}
    if chars_dir.exists():
        for char_dir in sorted(chars_dir.iterdir()):
            if char_dir.is_dir():
                characters[char_dir.name] = _relative_paths(char_dir)

    return {
        "backgrounds": _relative_paths(LAYERS_DIR / "backgrounds"),
        "midground": _relative_paths(LAYERS_DIR / "midground"),
        "foreground": _relative_paths(LAYERS_DIR / "foreground"),
        "characters": characters,
        "props": _relative_paths(LAYERS_DIR / "props"),
        "text": _relative_paths(LAYERS_DIR / "text"),
        "hidden_objects": _relative_paths(LAYERS_DIR / "hidden_objects"),
        "generated": _relative_paths(GENERATED_PAGES_DIR),
        "book_illustrations": list_book_illustration_assets(),
        "book_image_library": list_book_image_library_assets(),
    }


def list_book_illustration_assets() -> list[dict[str, Any]]:
    """Return generated book page illustrations grouped by book slug."""
    books_dir = PROJECT_ROOT / "books"
    if not books_dir.exists():
        return []
    groups: list[dict[str, Any]] = []
    for book_dir in sorted(books_dir.iterdir()):
        if not book_dir.is_dir():
            continue
        images = _relative_paths(book_dir / "illustrations")
        if not images:
            continue
        groups.append(
            {
                "slug": book_dir.name,
                "title": _book_title(book_dir),
                "count": len(images),
                "images": images,
            }
        )
    return groups


def list_book_image_library_assets() -> list[dict[str, Any]]:
    """Return all book-scoped generated images grouped by book and category."""
    books_dir = PROJECT_ROOT / "books"
    if not books_dir.exists():
        return []

    groups: list[dict[str, Any]] = []
    for book_dir in sorted(books_dir.iterdir()):
        if not book_dir.is_dir():
            continue
        slug = book_dir.name
        categories = [
            _book_image_category("illustrations", "Page Illustrations", book_dir / "illustrations"),
            _book_image_category("locked", "Locked Page Art", book_dir / "illustrations_locked"),
            _book_image_category("qa", "QA Candidates", book_dir / "qa_candidates"),
            _book_image_category("rejected", "Rejected QA Images", book_dir / "qa_rejected"),
            _book_image_category("reports", "Reports And Renders", book_dir / "reports"),
            _book_image_category("characters", "Character Layers", None, _book_character_layer_paths(slug)),
            _book_image_category("text", "Text Art Layers", LAYERS_DIR / "text" / slug),
        ]
        visible_categories = [category for category in categories if category["images"]]
        if not visible_categories:
            continue
        all_images = [
            path
            for category in visible_categories
            for path in category["images"]
        ]
        groups.append(
            {
                "slug": slug,
                "title": _book_title(book_dir),
                "count": len(all_images),
                "images": all_images,
                "categories": visible_categories,
            }
        )
    return groups


def _book_image_category(
    category_id: str,
    title: str,
    directory: Path | None,
    paths: list[str] | None = None,
) -> dict[str, Any]:
    images = paths if paths is not None else _relative_image_paths(directory or PROJECT_ROOT / "__missing__")
    return {
        "id": category_id,
        "title": title,
        "count": len(images),
        "images": images,
    }


def _book_character_layer_paths(book_slug: str) -> list[str]:
    characters_dir = LAYERS_DIR / "characters"
    if not characters_dir.exists():
        return []
    matches: list[Path] = []
    for custom_dir in characters_dir.glob("*/custom"):
        matches.extend(custom_dir.glob(f"{book_slug}*.png"))
        matches.extend(custom_dir.glob(f"{book_slug}*.jpg"))
        matches.extend(custom_dir.glob(f"{book_slug}*.jpeg"))
        matches.extend(custom_dir.glob(f"{book_slug}*.webp"))
    return sorted(path.relative_to(PROJECT_ROOT).as_posix() for path in matches if path.is_file())


def _book_title(book_dir: Path) -> str:
    book_yaml = book_dir / "book.yaml"
    if book_yaml.exists():
        try:
            data = yaml.safe_load(book_yaml.read_text(encoding="utf-8")) or {}
            title = str(data.get("title") or "").strip()
            if title:
                return title
        except (OSError, yaml.YAMLError):
            pass
    return book_dir.name.replace("_", " ").replace("-", " ").title()


def list_poses(character_slug: str) -> list[dict[str, Any]]:
    """Return poses from a character's poses.json manifest, or [] if absent."""
    poses_path = LAYERS_DIR / "characters" / character_slug / "poses.json"
    if not poses_path.exists():
        return []
    try:
        data = json.loads(poses_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    poses = data.get("poses", [])
    if character_slug == "niko":
        for pose in poses:
            pose_id = pose.get("id")
            niko_pose = NIKO_POSES.get(str(pose_id))
            if not niko_pose:
                continue
            pose.setdefault("asset_path", f"assets/layers/characters/niko/niko_{pose_id}.png")
            pose.setdefault("rig", _niko_rig(niko_pose))
    return poses


def _niko_rig(pose: Any) -> dict[str, Any]:
    return {
        "type": "niko_simple_v3",
        "bones": [
            {"id": "body_lean", "name": "Body Lean", "rotation": pose.body_lean, "min": -15, "max": 15},
            {"id": "head_tilt", "name": "Head Tilt", "rotation": pose.head_tilt, "min": -18, "max": 18},
            {"id": "antenna_tilt", "name": "Antenna Tilt", "rotation": pose.antenna_tilt, "min": -35, "max": 35},
            {"id": "left_upper_arm", "name": "Left Upper Arm", "rotation": pose.left_upper_arm, "min": -160, "max": 160},
            {"id": "left_forearm", "name": "Left Forearm", "rotation": pose.left_forearm, "min": -170, "max": 170},
            {"id": "left_hand", "name": "Left Hand", "rotation": pose.left_hand, "min": -45, "max": 45},
            {"id": "right_upper_arm", "name": "Right Upper Arm", "rotation": pose.right_upper_arm, "min": -160, "max": 160},
            {"id": "right_forearm", "name": "Right Forearm", "rotation": pose.right_forearm, "min": -170, "max": 170},
            {"id": "right_hand", "name": "Right Hand", "rotation": pose.right_hand, "min": -45, "max": 45},
            {"id": "left_thigh", "name": "Left Thigh", "rotation": pose.left_thigh, "min": 45, "max": 130},
            {"id": "left_shin", "name": "Left Shin", "rotation": pose.left_shin, "min": 45, "max": 135},
            {"id": "left_foot", "name": "Left Foot", "rotation": pose.left_foot, "min": -35, "max": 35},
            {"id": "right_thigh", "name": "Right Thigh", "rotation": pose.right_thigh, "min": 50, "max": 135},
            {"id": "right_shin", "name": "Right Shin", "rotation": pose.right_shin, "min": 45, "max": 135},
            {"id": "right_foot", "name": "Right Foot", "rotation": pose.right_foot, "min": -35, "max": 35},
        ],
    }
