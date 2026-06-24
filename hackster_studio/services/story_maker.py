"""Layered storybook scene loading and saving for the web story maker."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ..automation.niko_lock import NIKO_POSES, NikoPose, placement_for_page, render_pose_library
from ..config import LAYERS_DIR, PROJECT_ROOT

SCENE_ROOT = Path(os.getenv("HACKSTER_SCENE_ROOT", PROJECT_ROOT / "storybook_scenes"))
_BOOK_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def scene_path(book_slug: str, page_number: int) -> Path:
    if not _BOOK_SLUG_RE.fullmatch(book_slug):
        raise ValueError("book_slug may only contain letters, numbers, underscores, and hyphens")
    if page_number < 1:
        raise ValueError("page_number must be positive")
    return SCENE_ROOT / book_slug / f"page_{page_number:03d}.scene.json"


def load_scene(book_slug: str = "book01_password_dragon", page_number: int = 4) -> dict[str, Any]:
    path = scene_path(book_slug, page_number)
    if not path.exists():
        return default_scene(book_slug, page_number)
    return hydrate_scene(json.loads(path.read_text(encoding="utf-8")))


def save_scene(scene: dict[str, Any]) -> Path:
    missing = [k for k in ("book_slug", "page_number") if k not in scene]
    if missing:
        raise ValueError(f"Scene dict missing required keys: {missing}")
    scene = hydrate_scene(scene)
    scene["updated_at"] = utc_now()
    path = scene_path(scene["book_slug"], scene["page_number"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scene, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def book_page_count(book_slug: str) -> int:
    pages_dir = PROJECT_ROOT / "books" / book_slug / "pages"
    count = len(list(pages_dir.glob("page_*.yaml")))
    return count or 32


def book_illustration_path(book_slug: str, page_number: int) -> Path:
    return PROJECT_ROOT / "books" / book_slug / "illustrations" / f"page_{page_number:03d}.png"


def book_illustration_asset_path(book_slug: str, page_number: int) -> str | None:
    path = book_illustration_path(book_slug, page_number)
    if not path.exists():
        return None
    return path.relative_to(PROJECT_ROOT).as_posix()


def book_illustration_asset_version(book_slug: str, page_number: int) -> int | None:
    path = book_illustration_path(book_slug, page_number)
    if not path.exists():
        return None
    return int(path.stat().st_mtime_ns)


def book_page_metadata(book_slug: str, page_number: int) -> dict[str, Any]:
    path = PROJECT_ROOT / "books" / book_slug / "pages" / f"page_{page_number:03d}.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def planned_characters(book_slug: str) -> list[dict[str, Any]]:
    """Return book-planned characters so the editor can show cast members before art exists."""
    names: list[str] = []
    book_path = PROJECT_ROOT / "books" / book_slug / "book.yaml"
    if book_path.exists():
        data = yaml.safe_load(book_path.read_text(encoding="utf-8")) or {}
        brief = data.get("planner_brief") or {}
        names.extend(str(item).strip() for item in brief.get("focus_characters") or [])

    pages_dir = PROJECT_ROOT / "books" / book_slug / "pages"
    for page_path in sorted(pages_dir.glob("page_*.yaml")):
        try:
            page = yaml.safe_load(page_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        names.extend(str(item).strip() for item in page.get("characters") or [])

    seen: set[str] = set()
    planned: list[dict[str, Any]] = []
    for name in names:
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        slug = character_slug(name)
        asset_paths = [
            path.relative_to(PROJECT_ROOT).as_posix()
            for path in sorted((LAYERS_DIR / "characters" / slug).rglob("*.png"))
            if path.is_file()
        ] if (LAYERS_DIR / "characters" / slug).exists() else []
        planned.append({
            "name": name,
            "slug": slug,
            "asset_paths": asset_paths,
        })
    return planned


def character_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "character"


def book_uses_hackster_niko(book_slug: str) -> bool:
    book_path = PROJECT_ROOT / "books" / book_slug / "book.yaml"
    if not book_path.exists():
        return book_slug.startswith("book01_") or book_slug.startswith("hackster")
    data = yaml.safe_load(book_path.read_text(encoding="utf-8")) or {}
    title = str(data.get("title") or "").lower()
    if "hackster niko" in title:
        return True
    brief = data.get("planner_brief") or {}
    focus_characters = brief.get("focus_characters") or []
    return any(str(character).strip().lower() == "hackster niko" for character in focus_characters)


def hydrate_scene(scene: dict[str, Any]) -> dict[str, Any]:
    book_slug = str(scene.get("book_slug", "book01_password_dragon"))
    page_number = int(scene.get("page_number", 1))
    uses_niko = book_uses_hackster_niko(book_slug) and not bool(scene.get("suppress_hackster_niko"))
    scene["uses_hackster_niko"] = uses_niko
    scene["planned_characters"] = planned_characters(book_slug)
    scene["page_count"] = book_page_count(book_slug)
    scene.setdefault("status", "not_started")
    scene.setdefault("approval", {
        "approved": False,
        "approved_at": None,
        "approved_by": None,
        "notes": "",
    })
    scene.setdefault("prompt_history", [])
    scene.setdefault("created_at", utc_now())
    scene.setdefault("updated_at", scene["created_at"])
    scene.setdefault("production_notes", "")
    page_meta = book_page_metadata(book_slug, page_number)
    story_text = str(page_meta.get("story_text", "")).strip()
    if story_text:
        scene.setdefault("story_text", story_text)
    illustration = book_illustration_asset_path(book_slug, page_number)
    illustration_version = book_illustration_asset_version(book_slug, page_number)
    if illustration:
        scene["book_illustration_path"] = illustration
        if illustration_version is not None:
            scene["book_illustration_version"] = illustration_version
        layers = scene.setdefault("layers", [])
        layers[:] = [
            layer for layer in layers
            if not (
                layer.get("id") in {"char_niko", "bg_001"}
                and not layer.get("asset_path")
            )
        ]
        review_layer = next((layer for layer in layers if layer.get("id") == "book_illustration"), None)
        if review_layer is None:
            layers.insert(0, review_image_layer(illustration, asset_version=illustration_version))
        else:
            review_layer["asset_path"] = illustration
            if illustration_version is not None:
                review_layer["asset_version"] = illustration_version
        if uses_niko and not any(layer.get("id") == "char_niko" for layer in layers):
            niko_layer = review_niko_layer(page_number)
            if niko_layer:
                layers.append(niko_layer)
        elif uses_niko:
            niko_layer = next((layer for layer in layers if layer.get("id") == "char_niko"), None)
            if niko_layer:
                upgrade_niko_layer(niko_layer, page_number)
        else:
            layers[:] = [layer for layer in layers if layer.get("id") != "char_niko"]
        if story_text and not any(layer.get("type") == "text" for layer in layers):
            layers.append(review_text_layer(story_text))
    for layer in scene.setdefault("layers", []):
        hydrate_layer(layer)
    scene["qa"] = validate_scene(scene)
    return scene


def remove_hackster_niko_from_book(book_slug: str) -> dict[str, Any]:
    page_count = book_page_count(book_slug)
    pages_updated = 0
    layers_removed = 0
    for page_number in range(1, page_count + 1):
        scene = load_scene(book_slug, page_number)
        before = len(scene.get("layers", []))
        scene["layers"] = [
            layer for layer in scene.get("layers", [])
            if layer.get("id") != "char_niko" and str(layer.get("name", "")).strip().lower() != "hackster niko"
        ]
        removed = before - len(scene["layers"])
        scene["suppress_hackster_niko"] = True
        scene["uses_hackster_niko"] = False
        save_scene(scene)
        if removed:
            layers_removed += removed
        pages_updated += 1
    return {
        "book_slug": book_slug,
        "page_count": page_count,
        "pages_updated": pages_updated,
        "layers_removed": layers_removed,
    }


def hydrate_layer(layer: dict[str, Any]) -> dict[str, Any]:
    layer.setdefault("visible", True)
    layer.setdefault("locked", False)
    layer.setdefault("preserve_aspect", layer.get("type") in {"character", "props"})
    layer.setdefault("versions", [])
    layer.setdefault("prompt_history", [])
    transform = layer.setdefault("transform", {})
    if layer.get("type") not in {"camera", "lighting"}:
        transform.setdefault("x", 0.5)
        transform.setdefault("y", 0.5)
        transform.setdefault("width", 0.3)
        transform.setdefault("height", 0.3)
        transform.setdefault("scale", 1.0)
        transform.setdefault("rotation", 0)
        transform.setdefault("opacity", 1)
    return layer


def set_scene_status(
    book_slug: str,
    page_number: int,
    status: str,
    *,
    approved_by: str | None = None,
    notes: str = "",
) -> dict[str, Any]:
    allowed = {"not_started", "generated", "needs_edit", "approved", "exported"}
    if status not in allowed:
        raise ValueError(f"status must be one of: {', '.join(sorted(allowed))}")
    scene = load_scene(book_slug, page_number)
    scene["status"] = status
    scene["approval"] = scene.get("approval") or {}
    scene["approval"]["approved"] = status == "approved"
    scene["approval"]["approved_at"] = utc_now() if status == "approved" else None
    scene["approval"]["approved_by"] = approved_by if status == "approved" else None
    if notes:
        scene["approval"]["notes"] = notes
    save_scene(scene)
    return scene


def validate_scene(scene: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    layers = scene.get("layers", [])
    visible_layers = [layer for layer in layers if layer.get("visible", True)]
    canvas = scene.get("canvas", {})
    safe_margin = float(canvas.get("safe_margin_inches", 0.5))
    trim = canvas.get("trim_inches", [8.5, 8.5])
    trim_width = float(trim[0] if trim else 8.5)
    safe_pct = safe_margin / trim_width if trim_width else 0.0588

    has_background = any(
        layer.get("type") == "background" and layer.get("visible", True) and layer.get("asset_path")
        for layer in layers
    )
    has_text = any(layer.get("type") == "text" and layer.get("visible", True) for layer in layers)
    has_niko = any(layer.get("id") == "char_niko" and layer.get("visible", True) for layer in layers)

    if not has_background:
        issues.append({"severity": "error", "code": "missing_background", "message": "No visible background image layer."})
    if not has_text:
        issues.append({"severity": "warning", "code": "missing_text", "message": "No visible dialogue/text layer."})
    if scene.get("uses_hackster_niko", True) and not has_niko and scene.get("page_number", 0) >= 4:
        issues.append({"severity": "warning", "code": "missing_niko", "message": "Hackster Niko is not present as a separate layer."})

    for layer in visible_layers:
        transform = layer.get("transform") or {}
        x = float(transform.get("x", 0.5))
        y = float(transform.get("y", 0.5))
        width = float(transform.get("width", 1.0))
        height = float(transform.get("height", 1.0))
        left = x - width / 2
        right = x + width / 2
        top = y - height / 2
        bottom = y + height / 2

        if layer.get("type") == "text" and (left < safe_pct or top < safe_pct or right > 1 - safe_pct or bottom > 1 - safe_pct):
            issues.append({
                "severity": "error",
                "code": "text_outside_safe_area",
                "message": f"{layer.get('name', 'Text')} crosses the safe text margin.",
            })
        if width <= 0 or height <= 0:
            issues.append({
                "severity": "error",
                "code": "invalid_layer_size",
                "message": f"{layer.get('name', 'Layer')} has an invalid size.",
            })
        if layer.get("type") not in {"camera", "lighting", "text"} and not layer.get("asset_path"):
            issues.append({
                "severity": "warning",
                "code": "missing_asset",
                "message": f"{layer.get('name', 'Layer')} has no image asset.",
            })

    status = scene.get("status", "not_started")
    if status != "approved":
        issues.append({"severity": "info", "code": "not_approved", "message": "Page is not approved yet."})

    errors = sum(1 for issue in issues if issue["severity"] == "error")
    warnings = sum(1 for issue in issues if issue["severity"] == "warning")
    return {
        "ready": errors == 0 and status == "approved",
        "errors": errors,
        "warnings": warnings,
        "issues": issues,
    }


def book_readiness(book_slug: str) -> dict[str, Any]:
    page_count = book_page_count(book_slug)
    pages = []
    ready_count = 0
    approved_count = 0
    for page_number in range(1, page_count + 1):
        scene = load_scene(book_slug, page_number)
        qa = validate_scene(scene)
        status = scene.get("status", "not_started")
        approved = bool((scene.get("approval") or {}).get("approved"))
        if qa["ready"]:
            ready_count += 1
        if approved:
            approved_count += 1
        pages.append({
            "page_number": page_number,
            "status": status,
            "approved": approved,
            "ready": qa["ready"],
            "errors": qa["errors"],
            "warnings": qa["warnings"],
            "issues": qa["issues"],
            "thumbnail": scene.get("book_illustration_path"),
        })
    return {
        "book_slug": book_slug,
        "page_count": page_count,
        "approved_pages": approved_count,
        "ready_pages": ready_count,
        "ready": ready_count == page_count and page_count > 0,
        "pages": pages,
    }


def prepare_book_review_scenes(book_slug: str, *, overwrite_text: bool = True) -> dict[str, Any]:
    page_count = book_page_count(book_slug)
    prepared_pages: list[int] = []
    images_linked = 0
    text_layers_updated = 0

    for page_number in range(1, page_count + 1):
        scene = load_scene(book_slug, page_number)
        page_meta = book_page_metadata(book_slug, page_number)
        story_text = str(page_meta.get("story_text", "")).strip()
        illustration = book_illustration_asset_path(book_slug, page_number)
        illustration_version = book_illustration_asset_version(book_slug, page_number)

        scene["page_count"] = page_count
        scene["planned_characters"] = planned_characters(book_slug)
        for key in (
            "page_type",
            "scene_title",
            "illustration_direction",
            "characters",
            "environment",
            "emotion",
            "camera",
            "hidden_objects",
            "text_safe_area",
        ):
            if key in page_meta:
                scene[key] = page_meta[key]
        if story_text:
            scene["story_text"] = story_text

        layers = scene.setdefault("layers", [])
        if illustration:
            image_layer = next((layer for layer in layers if layer.get("id") == "book_illustration"), None)
            if image_layer is None:
                layers.insert(0, review_image_layer(illustration, asset_version=illustration_version))
            else:
                image_layer["name"] = "Current Page Illustration"
                image_layer["type"] = "background"
                image_layer["asset_path"] = illustration
                image_layer["locked"] = True
                image_layer.setdefault("z_index", 0)
                image_layer.setdefault("transform", review_image_layer(illustration)["transform"])
                if illustration_version is not None:
                    image_layer["asset_version"] = illustration_version
                hydrate_layer(image_layer)
            scene["book_illustration_path"] = illustration
            if illustration_version is not None:
                scene["book_illustration_version"] = illustration_version
            images_linked += 1

        if story_text:
            text_layer = next(
                (
                    layer for layer in layers
                    if layer.get("id") == "page_text" or layer.get("type") == "text"
                ),
                None,
            )
            if text_layer is None:
                text_layer = review_text_layer(story_text)
                layers.append(text_layer)
            elif overwrite_text or not str(text_layer.get("text", "")).strip():
                text_layer["text"] = story_text
                text_layer["id"] = text_layer.get("id") or "page_text"
                text_layer["name"] = text_layer.get("name") or "Page Text"
                text_layer["type"] = "text"
                hydrate_layer(text_layer)
            text_layers_updated += 1

        if book_uses_hackster_niko(book_slug):
            niko_layer = next((layer for layer in layers if layer.get("id") == "char_niko"), None)
            if niko_layer:
                upgrade_niko_layer(niko_layer, page_number)
                hydrate_layer(niko_layer)
            else:
                new_niko_layer = review_niko_layer(page_number)
                if new_niko_layer:
                    layers.append(new_niko_layer)
        else:
            layers[:] = [layer for layer in layers if layer.get("id") != "char_niko"]

        if scene.get("status") in {None, "", "not_started"}:
            scene["status"] = "generated"
        scene.setdefault("approval", {
            "approved": False,
            "approved_at": None,
            "approved_by": None,
            "notes": "",
        })
        save_scene(scene)
        prepared_pages.append(page_number)

    return {
        "book_slug": book_slug,
        "page_count": page_count,
        "prepared_pages": prepared_pages,
        "prepared_count": len(prepared_pages),
        "images_linked": images_linked,
        "text_layers_updated": text_layers_updated,
        "scene_root": (SCENE_ROOT / book_slug).as_posix(),
    }


TEXT_STYLE_KEYS = {
    "font_size",
    "text_color",
    "stroke_color",
    "box_color",
    "box_opacity",
    "align",
    "font_family",
    "style_prompt",
    "preserve_aspect",
}


def apply_text_style_to_all_pages(
    book_slug: str,
    source_page_number: int,
    *,
    layer_id: str = "page_text",
) -> dict[str, Any]:
    source_scene = load_scene(book_slug, source_page_number)
    source_layer = next(
        (
            layer for layer in source_scene.get("layers", [])
            if layer.get("id") == layer_id or layer.get("type") == "text"
        ),
        None,
    )
    if not source_layer:
        raise ValueError("source text layer not found")

    style = {key: source_layer.get(key) for key in TEXT_STYLE_KEYS if key in source_layer}
    transform = dict(source_layer.get("transform") or {})
    page_count = book_page_count(book_slug)
    updated_pages: list[int] = []

    for page_number in range(1, page_count + 1):
        scene = load_scene(book_slug, page_number)
        text_layer = next(
            (
                layer for layer in scene.get("layers", [])
                if layer.get("id") == layer_id or layer.get("type") == "text"
            ),
            None,
        )
        if text_layer is None:
            story_text = str(scene.get("story_text", "")).strip()
            if not story_text:
                story_text = str(book_page_metadata(book_slug, page_number).get("story_text", "")).strip()
            text_layer = review_text_layer(story_text)
            scene.setdefault("layers", []).append(text_layer)

        text_layer.update(style)
        text_layer["transform"] = dict(transform)
        text_layer["asset_path"] = None
        text_layer["asset_version"] = utc_now()
        hydrate_layer(text_layer)
        save_scene(scene)
        updated_pages.append(page_number)

    return {
        "book_slug": book_slug,
        "source_page_number": source_page_number,
        "layer_id": layer_id,
        "updated_pages": updated_pages,
        "updated_count": len(updated_pages),
    }


def review_image_layer(asset_path: str, *, asset_version: int | None = None) -> dict[str, Any]:
    layer = {
        "id": "book_illustration",
        "name": "Current Page Illustration",
        "type": "background",
        "z_index": 0,
        "parallax_factor": 0.0,
        "asset_path": asset_path,
        "locked": True,
        "transform": {
            "x": 0.5,
            "y": 0.5,
            "width": 1.0,
            "height": 1.0,
            "scale": 1.0,
            "rotation": 0,
            "opacity": 1,
        },
    }
    if asset_version is not None:
        layer["asset_version"] = asset_version
    return layer


def review_text_layer(story_text: str) -> dict[str, Any]:
    return {
        "id": "page_text",
        "name": "Page Text",
        "type": "text",
        "z_index": 20,
        "parallax_factor": 1.0,
        "text": story_text,
        "font_size": 0.045,
        "text_color": "#154c84",
        "stroke_color": "#F2C94C",
        "box_color": "#FFFFFF",
        "box_opacity": 0.84,
        "align": "center",
        "font_family": "rounded",
        "style_prompt": "",
        "text_art_variant": 0,
        "preserve_aspect": False,
        "transform": {
            "x": 0.5,
            "y": 0.82,
            "width": 0.78,
            "height": 0.17,
            "scale": 1.0,
            "rotation": 0,
            "opacity": 1,
        },
    }


def review_niko_layer(page_number: int) -> dict[str, Any] | None:
    placement = placement_for_page(page_number)
    if placement is None:
        return None
    asset_path = ensure_niko_pose_asset(placement.pose)
    aspect_ratio = 900 / 1100
    height = placement.height
    width = height * aspect_ratio
    return {
        "id": "char_niko",
        "name": "Hackster Niko",
        "type": "character",
        "z_index": 5,
        "parallax_factor": 1.0,
        "character_slug": "niko",
        "asset_path": asset_path,
        "pose": placement.pose,
        "rig": niko_rig_for_pose(placement.pose),
        "shadow": {
            "enabled": True,
            "angle": 270,
            "distance": 12,
            "blur": 8,
            "opacity": 0.24,
        },
        "transform": {
            "x": placement.center_x,
            "y": placement.base_y - (height / 2),
            "width": width,
            "height": height,
            "scale": 1.0,
            "rotation": 0,
            "opacity": 1,
        },
    }


def upgrade_niko_layer(layer: dict[str, Any], page_number: int) -> None:
    placement = placement_for_page(page_number)
    pose = str(layer.get("pose") or (placement.pose if placement else "stand_front"))
    if pose == "standing_neutral":
        pose = "stand_front"
    if pose not in NIKO_POSES:
        pose = placement.pose if placement else "stand_front"
    layer["pose"] = pose
    layer["character_slug"] = "niko"
    layer.setdefault("z_index", 5)
    layer.setdefault("parallax_factor", 1.0)
    if not layer.get("asset_path") or str(layer.get("asset_path", "")).endswith("_ambient_soft.png"):
        layer["asset_path"] = ensure_niko_pose_asset(pose)
    rig = layer.get("rig")
    if not rig or rig.get("type") != "niko_simple_v3":
        layer["rig"] = niko_rig_for_pose(pose)


def ensure_niko_pose_asset(pose: str) -> str:
    pose_dir = LAYERS_DIR / "characters" / "niko"
    pose_path = pose_dir / f"niko_{pose}.png"
    if not pose_path.exists():
        render_pose_library(pose_dir)
    return pose_path.relative_to(PROJECT_ROOT).as_posix()


def niko_rig_for_pose(pose: str) -> dict[str, Any]:
    niko_pose = NIKO_POSES.get(pose, NIKO_POSES["stand_front"])
    return {
        "type": "niko_simple_v3",
        "bones": [
            {"id": "body_lean", "name": "Body Lean", "rotation": niko_pose.body_lean, "min": -15, "max": 15},
            {"id": "head_tilt", "name": "Head Tilt", "rotation": niko_pose.head_tilt, "min": -18, "max": 18},
            {"id": "antenna_tilt", "name": "Antenna Tilt", "rotation": niko_pose.antenna_tilt, "min": -35, "max": 35},
            {"id": "left_upper_arm", "name": "Left Upper Arm", "rotation": niko_pose.left_upper_arm, "min": -160, "max": 160},
            {"id": "left_forearm", "name": "Left Forearm", "rotation": niko_pose.left_forearm, "min": -170, "max": 170},
            {"id": "left_hand", "name": "Left Hand", "rotation": niko_pose.left_hand, "min": -45, "max": 45},
            {"id": "right_upper_arm", "name": "Right Upper Arm", "rotation": niko_pose.right_upper_arm, "min": -160, "max": 160},
            {"id": "right_forearm", "name": "Right Forearm", "rotation": niko_pose.right_forearm, "min": -170, "max": 170},
            {"id": "right_hand", "name": "Right Hand", "rotation": niko_pose.right_hand, "min": -45, "max": 45},
            {"id": "left_thigh", "name": "Left Thigh", "rotation": niko_pose.left_thigh, "min": 45, "max": 130},
            {"id": "left_shin", "name": "Left Shin", "rotation": niko_pose.left_shin, "min": 45, "max": 135},
            {"id": "left_foot", "name": "Left Foot", "rotation": niko_pose.left_foot, "min": -35, "max": 35},
            {"id": "right_thigh", "name": "Right Thigh", "rotation": niko_pose.right_thigh, "min": 50, "max": 135},
            {"id": "right_shin", "name": "Right Shin", "rotation": niko_pose.right_shin, "min": 45, "max": 135},
            {"id": "right_foot", "name": "Right Foot", "rotation": niko_pose.right_foot, "min": -35, "max": 35},
        ],
    }


def niko_pose_from_rig(name: str, label: str, rig: dict[str, Any] | None) -> NikoPose:
    rotations = {
        str(bone.get("id")): int(float(bone.get("rotation", 0)))
        for bone in (rig or {}).get("bones", [])
    }
    base = NIKO_POSES.get(name, NIKO_POSES["stand_front"])
    return NikoPose(
        name=name,
        label=label,
        body_lean=rotations.get("body_lean", base.body_lean),
        head_tilt=rotations.get("head_tilt", base.head_tilt),
        antenna_tilt=rotations.get("antenna_tilt", base.antenna_tilt),
        left_upper_arm=rotations.get("left_upper_arm", rotations.get("left_arm", base.left_upper_arm)),
        left_forearm=rotations.get("left_forearm", base.left_forearm),
        left_hand=rotations.get("left_hand", base.left_hand),
        right_upper_arm=rotations.get("right_upper_arm", rotations.get("right_arm", base.right_upper_arm)),
        right_forearm=rotations.get("right_forearm", base.right_forearm),
        right_hand=rotations.get("right_hand", base.right_hand),
        left_thigh=rotations.get("left_thigh", rotations.get("left_leg", base.left_thigh)),
        left_shin=rotations.get("left_shin", base.left_shin),
        left_foot=rotations.get("left_foot", base.left_foot),
        right_thigh=rotations.get("right_thigh", rotations.get("right_leg", base.right_thigh)),
        right_shin=rotations.get("right_shin", base.right_shin),
        right_foot=rotations.get("right_foot", base.right_foot),
    )


def default_scene(book_slug: str, page_number: int) -> dict[str, Any]:
    layers = [
        {
            "id": "camera_001",
            "name": "Camera",
            "type": "camera",
            "z_index": 99,
            "transform": {"x": 0.0, "y": 0.0, "zoom": 1.0, "rotation": 0},
        },
        {
            "id": "lighting_001",
            "name": "Ambient Light",
            "type": "lighting",
            "z_index": 10,
            "tint_color": "#FFFFFF",
            "blend_mode": "multiply",
            "opacity": 0.0,
        },
        {
            "id": "bg_001",
            "name": "Background",
            "type": "background",
            "z_index": 0,
            "parallax_factor": 0.1,
            "asset_path": None,
            "lighting_variant": "ambient_soft",
            "transform": {
                "x": 0.0,
                "y": 0.0,
                "width": 1.5,
                "height": 1.5,
                "scale": 1.0,
                "rotation": 0,
                "opacity": 1,
            },
        },
    ]
    if book_uses_hackster_niko(book_slug):
        layers.insert(2, {
            "id": "char_niko",
            "name": "Hackster Niko",
            "type": "character",
            "z_index": 3,
            "parallax_factor": 1.0,
            "character_slug": "niko",
            "asset_path": None,
            "lighting_variant": "ambient_soft",
            "pose": "standing_neutral",
            "rig": None,
            "shadow": {
                "enabled": False,
                "angle": 270,
                "distance": 12,
                "blur": 8,
                "opacity": 0.3,
            },
            "transform": {
                "x": 0.5,
                "y": 0.6,
                "width": 0.2,
                "height": 0.4,
                "scale": 1.0,
                "rotation": 0,
                "opacity": 1,
            },
        })
    scene = {
        "book_slug": book_slug,
        "page_number": page_number,
        "page_count": book_page_count(book_slug),
        "canvas": {
            "trim_inches": [8.5, 8.5],
            "bleed_inches": 0.125,
            "safe_margin_inches": 0.5,
            "dpi": 300,
            "width_px": 2625,
            "height_px": 2625,
        },
        "lighting_brief": "ambient_soft",
        "layers": layers,
    }
    return hydrate_scene(scene)
