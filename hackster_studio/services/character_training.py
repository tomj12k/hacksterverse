"""Character selection and LoRA training manifests."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

import yaml

from ..config import LAYERS_DIR, PROJECT_ROOT
from ..pathsafe import require_safe_slug
from .story_maker import character_slug


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
REFERENCE_PACK_DIRS = {"references", "expressions", "poses", "samples", "prompts", "qa"}
REFERENCE_PACK_FILES = {"character_reference_pack.json"}
DESIGN_LOCK_FILE = "design_lock.md"


def character_training_bench(name: str, slug: str | None = None) -> dict[str, Any]:
    """Return all UI data for choosing examples and preparing a character LoRA."""
    clean_slug = slug or character_slug(name)
    root = _character_root(clean_slug)
    manifest = load_training_manifest(clean_slug, name=name)
    images = list_character_training_images(clean_slug)
    selected = set(manifest.get("selected_images") or [])
    for image in images:
        image["selected"] = image["path"] in selected
    reference_manifest = _load_json(root / "character_reference_pack.json")
    return {
        "name": name,
        "slug": clean_slug,
        "root": root,
        "root_rel": _rel(root),
        "images": images,
        "selected_count": len(selected),
        "manifest": manifest,
        "reference_manifest": reference_manifest,
        "design_lock": load_character_design_lock(clean_slug, name=name),
        "design_lock_path": _rel(root / DESIGN_LOCK_FILE),
        "ready_for_lora": len(selected) >= 20,
        "minimum_lora_images": 20,
        "target_lora_images": 40,
    }


def load_character_design_lock(slug: str, *, name: str = "") -> str:
    path = _character_root(slug) / DESIGN_LOCK_FILE
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return default_character_design_lock(name or slug.replace("_", " ").title())


def save_character_design_lock(slug: str, design_lock: str, *, name: str = "") -> dict[str, Any]:
    clean_text = design_lock.strip() or default_character_design_lock(name or slug.replace("_", " ").title())
    path = _character_root(slug) / DESIGN_LOCK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(clean_text.rstrip() + "\n", encoding="utf-8")
    manifest = load_training_manifest(slug, name=name)
    manifest["design_lock_path"] = _rel(path)
    manifest["last_training_message"] = "Character design lock saved. Regenerate the reference pack to apply it to new prompts."
    manifest["updated_at"] = _now()
    _write_json(_training_manifest_path(slug), manifest)
    return manifest


def default_character_design_lock(name: str) -> str:
    return (
        f"{name} is one exact recurring character, not a generic archetype. "
        "If an approved front reference exists, match that reference as the source of truth. "
        "Preserve the same head/helmet outline, face layout, body proportions, costume silhouette, material finish, "
        "color placement, markings, and recognizable props or motifs. "
        "Only the pose, camera angle, and expression may change. "
        "Do not redesign the character, change species/body type, swap outfits, simplify details, add new limbs, or create a different character with the same name."
    )


def list_asset_character_cards() -> list[dict[str, Any]]:
    characters_root = LAYERS_DIR / "characters"
    if not characters_root.exists():
        return []
    cards: list[dict[str, Any]] = []
    for path in sorted(characters_root.iterdir()):
        if not path.is_dir():
            continue
        bench = character_training_bench(path.name.replace("_", " ").title(), path.name)
        preview = next((image["path"] for image in bench["images"] if image["kind"] in {"references", "custom", "poses"}), "")
        cards.append(
            {
                "slug": path.name,
                "name": bench["manifest"].get("character_name") or path.name.replace("_", " ").title(),
                "image_count": len(bench["images"]),
                "selected_count": bench["selected_count"],
                "status": bench["manifest"].get("status", "needs_examples"),
                "preview": preview,
            }
        )
    return cards


def list_character_training_images(slug: str) -> list[dict[str, Any]]:
    root = _character_root(slug)
    if not root.exists():
        return []
    images: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        if "/lora/" in path.as_posix():
            continue
        rel = _rel(path)
        images.append(
            {
                "path": rel,
                "label": path.stem.replace("_", " ").title(),
                "kind": _asset_kind(root, path),
                "selected": False,
            }
        )
    return images


def load_training_manifest(slug: str, *, name: str = "") -> dict[str, Any]:
    path = _training_manifest_path(slug)
    if path.exists():
        data = _load_json(path)
        if data:
            return _with_defaults(data, slug=slug, name=name)
    return _with_defaults({}, slug=slug, name=name)


def minimum_lora_images() -> int:
    """Minimum selected examples before LoRA training auto-submits."""
    return int(os.getenv("HACKSTER_LORA_MIN_IMAGES", "20"))


def training_status_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    """Compact, JSON-friendly status for the training UI / fetch responses."""
    selected = manifest.get("selected_images") or []
    minimum = minimum_lora_images()
    return {
        "status": str(manifest.get("status") or "needs_examples"),
        "selected_count": len(selected),
        "minimum": minimum,
        "ready": len(selected) >= minimum,
        "message": str(manifest.get("last_training_message") or ""),
        "training_pid": manifest.get("training_pid"),
    }


def save_training_selection(slug: str, selected_images: list[str], *, name: str = "") -> dict[str, Any]:
    allowed = {image["path"] for image in list_character_training_images(slug)}
    clean_selection = sorted(path for path in selected_images if path in allowed)
    manifest = load_training_manifest(slug, name=name)
    manifest["selected_images"] = clean_selection
    manifest["status"] = "examples_selected" if clean_selection else "needs_examples"
    manifest["updated_at"] = _now()
    _write_json(_training_manifest_path(slug), manifest)
    return manifest


def delete_character_image(slug: str, image_path: str, *, name: str = "") -> dict[str, Any]:
    """Delete a single character image and remove it from LoRA selection state."""
    return delete_character_images(slug, [image_path], name=name)


def delete_character_images(slug: str, image_paths: list[str], *, name: str = "") -> dict[str, Any]:
    """Delete selected character images and remove them from LoRA selection state."""
    root = _character_root(slug).resolve()
    lora_root = _lora_root(slug).resolve()
    deleted: list[str] = []
    for image_path in dict.fromkeys(path for path in image_paths if path):
        target = _project_asset_path(image_path).resolve()
        if root != target and root not in target.parents:
            raise ValueError("Image must be inside this character's asset folder.")
        if lora_root in target.parents:
            raise ValueError("Use LoRA controls to manage LoRA files; image deletion does not remove training outputs.")
        if target.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ValueError("Only character image files can be deleted.")
        if target.exists():
            target.unlink()
            deleted.append(image_path)
    manifest = load_training_manifest(slug, name=name)
    deleted_set = set(deleted or image_paths)
    selected = [path for path in manifest.get("selected_images", []) if path not in deleted_set]
    manifest["selected_images"] = selected
    manifest["status"] = "examples_selected" if selected else "needs_examples"
    manifest["last_training_message"] = (
        f"Deleted {len(deleted)} selected character images." if len(deleted) != 1 else f"Deleted image: {deleted[0]}"
    )
    manifest["updated_at"] = _now()
    _write_json(_training_manifest_path(slug), manifest)
    if manifest.get("dataset_manifest") or manifest.get("training_request"):
        prepare_lora_dataset(slug, name=name)
    return manifest


def delete_reference_pack(slug: str, *, name: str = "") -> dict[str, Any]:
    """Delete generated reference-pack folders/files while preserving LoRA data."""
    root = _character_root(slug)
    deleted: list[str] = []
    for dirname in sorted(REFERENCE_PACK_DIRS):
        path = root / dirname
        if path.exists():
            shutil.rmtree(path)
            deleted.append(_rel(path))
    for filename in sorted(REFERENCE_PACK_FILES):
        path = root / filename
        if path.exists():
            path.unlink()
            deleted.append(_rel(path))

    manifest = load_training_manifest(slug, name=name)
    remaining = {image["path"] for image in list_character_training_images(slug)}
    manifest["selected_images"] = [path for path in manifest.get("selected_images", []) if path in remaining]
    manifest["status"] = "examples_selected" if manifest["selected_images"] else "needs_examples"
    manifest["last_training_message"] = (
        f"Deleted reference pack files for {name or slug}. LoRA training files were preserved."
    )
    manifest["deleted_reference_pack_paths"] = deleted
    manifest["updated_at"] = _now()
    _write_json(_training_manifest_path(slug), manifest)
    if manifest.get("dataset_manifest") or manifest.get("training_request"):
        prepare_lora_dataset(slug, name=name)
    return manifest


def process_training_selection(slug: str, selected_images: list[str], *, name: str = "") -> dict[str, Any]:
    """Save a picked example set and advance every safe downstream step."""
    manifest = save_training_selection(slug, selected_images, name=name)
    manifest = prepare_lora_dataset(slug, name=name)
    if len(manifest.get("selected_images") or []) >= int(os.getenv("HACKSTER_LORA_MIN_IMAGES", "20")):
        manifest = _start_lora_training(slug, name=name, auto=True)
    else:
        remaining = int(os.getenv("HACKSTER_LORA_MIN_IMAGES", "20")) - len(manifest.get("selected_images") or [])
        manifest["last_training_message"] = (
            f"Selection saved and LoRA dataset refreshed. Pick {max(0, remaining)} more strong examples before DGX training submits automatically."
        )
        manifest["updated_at"] = _now()
        _write_json(_training_manifest_path(slug), manifest)
    return manifest


def prepare_lora_dataset(slug: str, *, name: str = "") -> dict[str, Any]:
    manifest = load_training_manifest(slug, name=name)
    selected = list(manifest.get("selected_images") or [])
    dataset = {
        "schema_version": 1,
        "character_slug": slug,
        "character_name": manifest.get("character_name") or name or slug,
        "created_at": _now(),
        "minimum_images": 20,
        "target_images": 40,
        "image_count": len(selected),
        "images": [
            {
                "path": path,
                "caption": _caption_for(manifest.get("character_name") or name or slug, path),
            }
            for path in selected
        ],
    }
    dataset_path = _lora_root(slug) / "dataset_manifest.json"
    _write_json(dataset_path, dataset)

    request = {
        "schema_version": 1,
        "character_slug": slug,
        "character_name": dataset["character_name"],
        "status": "ready_to_train" if len(selected) >= 20 else "needs_more_examples",
        "base_model": os.getenv("HACKSTER_LORA_BASE_MODEL", "flux1-dev.safetensors"),
        "trainer": os.getenv("HACKSTER_LORA_TRAINER", "configured_dgx_command"),
        "rank": int(os.getenv("HACKSTER_LORA_RANK", "16")),
        "network_alpha": int(os.getenv("HACKSTER_LORA_ALPHA", "16")),
        "resolution": int(os.getenv("HACKSTER_LORA_RESOLUTION", "1024")),
        "dataset_manifest": _rel(dataset_path),
        "output_dir": _rel(_lora_root(slug) / "outputs"),
        "recommended_trigger": _trigger_for(dataset["character_name"]),
        "notes": (
            "Curate 20-40 clean, consistent examples before training. Reject anatomy drift, duplicate body plans, "
            "and off-model outfits. Use ControlNet only for pose/layout; identity should come from the LoRA plus references."
        ),
        "updated_at": _now(),
    }
    request_path = _lora_root(slug) / "lora_training_request.yaml"
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(yaml.safe_dump(request, sort_keys=False), encoding="utf-8")

    manifest["dataset_manifest"] = _rel(dataset_path)
    manifest["training_request"] = _rel(request_path)
    manifest["status"] = request["status"]
    manifest["updated_at"] = _now()
    _write_json(_training_manifest_path(slug), manifest)
    return manifest


def _start_lora_training(slug: str, *, name: str = "", auto: bool = False) -> dict[str, Any]:
    previous = load_training_manifest(slug, name=name)
    manifest = prepare_lora_dataset(slug, name=name)
    selected_count = len(manifest.get("selected_images") or [])
    minimum = int(os.getenv("HACKSTER_LORA_MIN_IMAGES", "20"))
    if selected_count < minimum:
        manifest["status"] = "needs_more_examples"
        manifest["last_training_message"] = (
            f"LoRA dataset refreshed with {selected_count} examples. Pick at least {minimum} before training."
        )
        manifest["updated_at"] = _now()
        _write_json(_training_manifest_path(slug), manifest)
        return manifest
    if auto and previous.get("status") == "training_submitted" and not _truthy(os.getenv("HACKSTER_LORA_ALLOW_RESUBMIT", "")):
        manifest["last_training_message"] = "Selection saved. Training is already submitted; set HACKSTER_LORA_ALLOW_RESUBMIT=1 to submit again."
        manifest["updated_at"] = _now()
        _write_json(_training_manifest_path(slug), manifest)
        return manifest
    command = os.getenv("HACKSTER_DGX_LORA_TRAIN_COMMAND", "").strip()
    if not command:
        manifest["status"] = "ready_to_train"
        manifest["last_training_message"] = (
            "LoRA dataset is ready. Set HACKSTER_DGX_LORA_TRAIN_COMMAND to submit training on the DGX automatically."
        )
        manifest["updated_at"] = _now()
        _write_json(_training_manifest_path(slug), manifest)
        return manifest

    output_dir = _lora_root(slug) / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "HACKSTER_CHARACTER_SLUG": slug,
            "HACKSTER_CHARACTER_NAME": str(manifest.get("character_name") or name or slug),
            "HACKSTER_LORA_DATASET_MANIFEST": str((PROJECT_ROOT / str(manifest["dataset_manifest"])).resolve()),
            "HACKSTER_LORA_OUTPUT_DIR": str(output_dir.resolve()),
        }
    )
    # Capture the launcher's output to a log so the run is visible instead of
    # detaching silently. The child inherits the fd; the parent handle is closed
    # right after spawn.
    train_log = _lora_root(slug) / "train.log"
    log_handle = open(train_log, "a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            shlex.split(command), cwd=PROJECT_ROOT, env=env, stdout=log_handle, stderr=subprocess.STDOUT
        )
    finally:
        log_handle.close()
    manifest["status"] = "training_submitted"
    manifest["training_pid"] = proc.pid
    manifest["training_log"] = _rel(train_log)
    manifest["last_training_message"] = (
        f"Submitted DGX LoRA training (PID {proc.pid}). Output log: {_rel(train_log)}"
    )
    manifest["updated_at"] = _now()
    _write_json(_training_manifest_path(slug), manifest)
    return manifest


def start_lora_training(slug: str, *, name: str = "") -> dict[str, Any]:
    return _start_lora_training(slug, name=name, auto=False)


def save_lora_settings(
    slug: str,
    *,
    name: str = "",
    lora_name: str = "",
    lora_path: str = "",
    trigger: str = "",
) -> dict[str, Any]:
    manifest = load_training_manifest(slug, name=name)
    manifest["active_lora"] = {
        "name": lora_name.strip(),
        "path": lora_path.strip(),
        "trigger": trigger.strip() or _trigger_for(name or manifest.get("character_name") or slug),
        "status": "active" if (lora_name.strip() or lora_path.strip()) else "not_configured",
    }
    manifest["status"] = "lora_active" if manifest["active_lora"]["status"] == "active" else manifest.get("status", "needs_examples")
    manifest["updated_at"] = _now()
    _write_json(_training_manifest_path(slug), manifest)
    return manifest


def active_lora_for_character(slug: str) -> dict[str, str]:
    manifest = load_training_manifest(slug)
    active = manifest.get("active_lora") or {}
    if active.get("status") != "active":
        return {}
    return {
        "name": str(active.get("name") or ""),
        "path": str(active.get("path") or ""),
        "trigger": str(active.get("trigger") or ""),
    }


def character_slug_from_output_path(output_path: str) -> str | None:
    parts = Path(output_path).parts
    needle = ("assets", "layers", "characters")
    for index in range(len(parts) - len(needle)):
        if tuple(parts[index:index + len(needle)]) == needle and len(parts) > index + len(needle):
            return parts[index + len(needle)]
    return None


@contextmanager
def lora_environment_for_character(slug: str | None) -> Iterator[None]:
    active = active_lora_for_character(slug or "") if slug else {}
    values: dict[str, str] = {}
    lora_name = active.get("name") or Path(active.get("path") or "").name
    if lora_name:
        values["COMFYUI_LORA_NAME"] = lora_name
        values["COMFYUI_LORA_STRENGTH_MODEL"] = os.getenv("COMFYUI_LORA_STRENGTH_MODEL", "0.85")
        values["COMFYUI_LORA_STRENGTH_CLIP"] = os.getenv("COMFYUI_LORA_STRENGTH_CLIP", "0.85")
    with _temporary_environ(values):
        yield


def _with_defaults(data: dict[str, Any], *, slug: str, name: str = "") -> dict[str, Any]:
    data = dict(data)
    data.setdefault("schema_version", 1)
    data.setdefault("character_slug", slug)
    data.setdefault("character_name", name or slug.replace("_", " ").title())
    data.setdefault("selected_images", [])
    data.setdefault("status", "needs_examples")
    data.setdefault("active_lora", {"status": "not_configured", "name": "", "path": "", "trigger": _trigger_for(name or slug)})
    data.setdefault("created_at", _now())
    data.setdefault("updated_at", data["created_at"])
    return data


def _asset_kind(root: Path, path: Path) -> str:
    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        return "asset"
    if len(rel_parts) > 1:
        return rel_parts[0]
    return "root"


def _caption_for(name: str, path: str) -> str:
    label = Path(path).stem.replace("_", " ")
    return f"{_trigger_for(name)}, {name}, consistent character reference, {label}"


def _trigger_for(name: str) -> str:
    slug = character_slug(name)
    return f"{slug}_character"


def _training_manifest_path(slug: str) -> Path:
    return _lora_root(slug) / "training_manifest.json"


def _lora_root(slug: str) -> Path:
    return _character_root(slug) / "lora"


def _character_root(slug: str) -> Path:
    # Chokepoint for every character LoRA path (_lora_root and
    # _training_manifest_path both route through here). Reject traversal slugs
    # so no downstream write/glob/delete can escape the characters directory.
    return LAYERS_DIR / "characters" / require_safe_slug(slug)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _project_asset_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute() or not path.strip():
        raise ValueError("Image path must be a project-relative path.")
    resolved = (PROJECT_ROOT / candidate).resolve()
    project_root = PROJECT_ROOT.resolve()
    if resolved != project_root and project_root not in resolved.parents:
        raise ValueError("Image path must stay inside the project.")
    return resolved


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@contextmanager
def _temporary_environ(values: dict[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
