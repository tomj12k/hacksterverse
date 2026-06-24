"""Character reference pack generation for layered book production."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterator

import yaml
from PIL import Image, ImageStat

from ..config import PROJECT_ROOT
from ..services.story_maker import character_slug
from .comfyui_engine import generate_image_comfyui
from .dgx_services import release_dgx_planner_for_images
from .transparent_png import make_background_transparent


TURNAROUND_VIEWS = ["front", "side", "back", "three_quarter"]
EXPRESSIONS = ["happy", "focused", "surprised", "determined", "curious", "proud"]
POSES = ["standing_neutral", "walking", "pointing", "holding_object", "thinking", "celebrating"]
MIN_EXPRESSIONS = 5
MIN_POSES = 5
DEFAULT_REFERENCE_IMAGE_COUNT = len(TURNAROUND_VIEWS) + len(EXPRESSIONS) + len(POSES)
MAX_REFERENCE_IMAGE_COUNT = 100
NIKO_REFERENCE_LOCK = (
    "Hackster Niko, model HN-01, is a small friendly learning robot with a rounded helmet head, "
    "one tiny antenna with glowing blue tip, glossy white shell, dark glass face screen with exactly two glowing cyan-blue eyes, "
    "blue hoodie, centered cyan Core Crystal, compact floating magnetic backpack, rounded robot arms and legs, "
    "and no mouth, tail, wings, animal ears, snout, claws, paws, horns, fur, organic skin, or extra appendages."
)


@dataclass
class CharacterReferenceItem:
    kind: str
    label: str
    path: str
    prompt_path: str
    status: str
    qa: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass
class CharacterReferencePackResult:
    name: str
    slug: str
    root: Path
    manifest_path: Path
    items: list[CharacterReferenceItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    ready: bool = False

    @property
    def generated_count(self) -> int:
        return len([item for item in self.items if item.status == "generated"])

    @property
    def skipped_count(self) -> int:
        return len([item for item in self.items if item.status == "skipped"])


@dataclass
class CharacterReferenceRunResult:
    book_slug: str
    packs: list[CharacterReferencePackResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    ready: bool = True

    @property
    def character_count(self) -> int:
        return len(self.packs)

    @property
    def image_count(self) -> int:
        return sum(len(pack.items) for pack in self.packs)


def generate_character_reference_packs(
    *,
    book_slug: str,
    book: dict[str, Any] | None = None,
    pages: list[dict[str, Any]] | None = None,
    project_root: Path | None = None,
    force: bool = False,
    image_count_per_character: int | None = None,
    manage_dgx_image_profile: bool = True,
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    console: Any | None = None,
) -> CharacterReferenceRunResult:
    """Generate and QA reusable character reference packs for a book."""
    root = project_root or PROJECT_ROOT
    book_data = book or _load_book(root, book_slug)
    page_data = pages if pages is not None else _load_pages(root, book_slug)
    characters = _book_characters(book_data, page_data)
    requested_count = _reference_image_count(image_count_per_character)
    result = CharacterReferenceRunResult(book_slug=book_slug)
    _emit(
        progress_callback,
        "characters_started",
        book_slug=book_slug,
        characters=len(characters),
        image_count_per_character=requested_count,
        message=f"Starting character reference gate for {len(characters)} characters, {requested_count} images each.",
    )

    if not characters:
        _emit(progress_callback, "characters_done", book_slug=book_slug, characters=0, images=0, message="No planned characters found for this book.")
        return result

    if manage_dgx_image_profile:
        release_dgx_planner_for_images(console=console)

    total = len(characters)
    for index, character_name in enumerate(characters, start=1):
        pack = _generate_pack(
            book_slug=book_slug,
            book=book_data,
            character_name=character_name,
            project_root=root,
            force=force,
            character_index=index,
            total_characters=total,
            requested_count=requested_count,
            progress_callback=progress_callback,
        )
        result.packs.append(pack)
        result.errors.extend(pack.errors)

    result.ready = not result.errors and all(pack.ready for pack in result.packs)
    _emit(
        progress_callback,
        "characters_done",
        book_slug=book_slug,
        characters=result.character_count,
        images=result.image_count,
        errors=len(result.errors),
        ready=result.ready,
        message=f"Character reference gate finished: {result.character_count} characters, {result.image_count} reference images.",
    )
    return result


def _generate_pack(
    *,
    book_slug: str,
    book: dict[str, Any],
    character_name: str,
    project_root: Path,
    force: bool,
    character_index: int,
    total_characters: int,
    progress_callback: Callable[[str, dict[str, Any]], None] | None,
    requested_count: int,
) -> CharacterReferencePackResult:
    slug = character_slug(character_name)
    pack_root = project_root / "assets" / "layers" / "characters" / slug
    references_dir = pack_root / "references"
    expressions_dir = pack_root / "expressions"
    poses_dir = pack_root / "poses"
    samples_dir = pack_root / "samples"
    identity_dir = pack_root / "identity"
    prompts_dir = pack_root / "prompts"
    qa_dir = pack_root / "qa"
    for directory in (references_dir, expressions_dir, poses_dir, samples_dir, identity_dir, prompts_dir, qa_dir):
        directory.mkdir(parents=True, exist_ok=True)

    pack = CharacterReferencePackResult(
        name=character_name,
        slug=slug,
        root=pack_root,
        manifest_path=pack_root / "character_reference_pack.json",
    )
    design_lock = _character_design_lock(project_root, slug, character_name, book, pack_root)
    tasks = _reference_tasks(slug, references_dir, expressions_dir, poses_dir, samples_dir, requested_count)
    total_items = len(tasks)
    anchor_path = _identity_reference_path(pack_root, references_dir, slug)

    for item_index, (kind, label, image_path) in enumerate(tasks, start=1):
        prompt = _reference_prompt(book, character_name, kind, label, design_lock=design_lock)
        prompt_path = prompts_dir / f"{image_path.stem}.md"
        prompt_path.write_text(prompt.rstrip() + "\n", encoding="utf-8")
        event_payload = {
            "book_slug": book_slug,
            "character": character_name,
            "character_slug": slug,
            "character_index": character_index,
            "total_characters": total_characters,
            "item_index": item_index,
            "total_items": total_items,
            "kind": kind,
            "label": label,
            "path": image_path.as_posix(),
        }
        if image_path.exists() and not force:
            make_background_transparent(image_path)
            qa = _qa_image(image_path)
            pack.items.append(_item(kind, label, image_path, prompt_path, "skipped", qa=qa))
            if not qa.get("pass"):
                error = f"{character_name} existing {kind} {label} failed QA: {', '.join(qa.get('notes', []))}"
                pack.errors.append(error)
                pack.items[-1].status = "failed"
                pack.items[-1].error = error
                _emit(progress_callback, "character_reference_failed", **event_payload, error=error, message=error)
            else:
                _emit(progress_callback, "character_reference_skipped", **event_payload, message=f"{character_name}: kept existing {kind} {label}.")
            continue
        try:
            _emit(progress_callback, "character_reference_started", **event_payload, message=f"{character_name}: generating {kind} {label}.")
            reference_path = anchor_path if anchor_path and anchor_path.exists() and image_path != anchor_path else None
            _generate_reference_image(prompt, image_path, reference_path)
            qa = _qa_image(image_path)
            status = "generated" if qa.get("pass") else "failed"
            if not qa.get("pass"):
                error = f"{character_name} {kind} {label} failed QA: {', '.join(qa.get('notes', []))}"
                pack.errors.append(error)
                pack.items.append(_item(kind, label, image_path, prompt_path, status, qa=qa, error=error))
                _emit(progress_callback, "character_reference_failed", **event_payload, error=error, message=error)
            else:
                pack.items.append(_item(kind, label, image_path, prompt_path, status, qa=qa))
                _emit(progress_callback, "character_reference_done", **event_payload, message=f"{character_name}: finished {kind} {label}.")
        except Exception as exc:
            error = f"{character_name} {kind} {label}: {exc}"
            pack.errors.append(error)
            pack.items.append(_item(kind, label, image_path, prompt_path, "failed", error=error))
            _emit(progress_callback, "character_reference_failed", **event_payload, error=str(exc), message=error)
            _write_manifest(book_slug, book, pack, requested_count=requested_count)
            if _is_generation_infrastructure_error(exc):
                break
        _write_manifest(book_slug, book, pack, requested_count=requested_count)

    pack.ready = _pack_ready(pack, requested_count=requested_count)
    _write_manifest(book_slug, book, pack, requested_count=requested_count)
    _write_qa_report(pack)
    return pack


def _generate_reference_image(prompt: str, output_path: Path, reference_path: Path | None) -> Path:
    width = os.getenv("HACKSTER_CHARACTER_WIDTH", "1536")
    height = os.getenv("HACKSTER_CHARACTER_HEIGHT", "1536")
    workflow_path = _workflow_path(reference_path is not None)
    env = {
        "COMFYUI_GENERATION_WIDTH": width,
        "COMFYUI_GENERATION_HEIGHT": height,
        "COMFYUI_WIDTH": width,
        "COMFYUI_HEIGHT": height,
        "COMFYUI_OUTPUT_PREFIX": f"hackster_characters/{output_path.parent.parent.name}",
        "COMFYUI_NEGATIVE_PROMPT": _character_negative_prompt(),
    }
    if reference_path is not None:
        if not reference_path.exists():
            raise FileNotFoundError(f"Character identity reference not found: {reference_path}")
        env["COMFYUI_REFERENCE_IMAGE"] = reference_path.as_posix()
        if workflow_path is None:
            env["COMFYUI_WORKFLOW_KIND"] = os.getenv("COMFYUI_CHARACTER_REFERENCE_WORKFLOW_KIND", "flux_pulid")
        # PuLID is a human-face identity model; on stylized mask faces (e.g.
        # Samurai Splat) it latches onto the dark eye/brow markings and stamps a
        # black mask onto every variant. Lower weight + earlier end_at let the
        # prompt's red-and-cream face and bright lighting reassert in late steps.
        env["COMFYUI_PULID_WEIGHT"] = os.getenv("COMFYUI_CHARACTER_REFERENCE_WEIGHT", os.getenv("COMFYUI_PULID_WEIGHT", "0.75"))
        env["COMFYUI_PULID_START_AT"] = os.getenv("COMFYUI_CHARACTER_REFERENCE_START_AT", os.getenv("COMFYUI_PULID_START_AT", "0.0"))
        env["COMFYUI_PULID_END_AT"] = os.getenv("COMFYUI_CHARACTER_REFERENCE_END_AT", os.getenv("COMFYUI_PULID_END_AT", "0.55"))
    with _temporary_environ(env):
        path = generate_image_comfyui(prompt, output_path, workflow_path=workflow_path)
    if path.exists():
        make_background_transparent(path)
    return path


def _is_generation_infrastructure_error(exc: Exception) -> bool:
    message = str(exc)
    return (
        "ComfyUI prompt" in message
        or "ComfyUI request failed" in message
        or "ComfyUI /prompt did not return prompt_id" in message
    )


def _workflow_path(reference_variant: bool) -> Path | None:
    key = "COMFYUI_CHARACTER_REFERENCE_WORKFLOW_PATH" if reference_variant else "COMFYUI_CHARACTER_WORKFLOW_PATH"
    raw = os.getenv(key) or os.getenv("COMFYUI_CHARACTER_WORKFLOW_PATH")
    return Path(raw).expanduser() if raw else None


def _reference_conditioning_configured() -> bool:
    if _workflow_path(True):
        return True
    workflow_kind = os.getenv("COMFYUI_CHARACTER_REFERENCE_WORKFLOW_KIND", "flux_pulid").lower()
    return workflow_kind in {"flux_pulid", "pulid_flux", "flux_redux", "redux_flux", "flux_kontext", "kontext_flux"}


def _reference_prompt(book: dict[str, Any], character_name: str, kind: str, label: str, *, design_lock: str) -> str:
    title = str(book.get("title") or "Untitled Book")
    style = str(book.get("global_illustration_style") or "")
    brief = book.get("planner_brief") or {}
    reference_notes = str(brief.get("reference_notes") or "").strip()
    focus_items = ", ".join(str(item) for item in (brief.get("focus_items") or []))
    identity_lock = ""
    if character_name.strip().lower() == "hackster niko":
        identity_lock = f"\nIdentity lock:\n{book.get('niko_consistency') or NIKO_REFERENCE_LOCK}\n"
    if kind == "turnaround":
        task = f"Create one full-body {label.replace('_', ' ')} view of the exact same character."
    elif kind == "expression":
        task = f"Create one clean {label.replace('_', ' ')} expression of the exact same character."
    elif kind == "pose":
        task = f"Create one full-body {label.replace('_', ' ')} pose of the exact same character."
    else:
        task = (
            f"Create close-match production sample {label.replace('_', ' ')} for the exact same character. "
            "Keep identity, proportions, silhouette, colors, outfit, face/body design, and materials as close as possible to the reference; vary only a tiny natural pose or expression detail."
        )
    allowed_change = {
        "turnaround": f"view angle only: {label.replace('_', ' ')}",
        "expression": f"facial/eye expression only: {label.replace('_', ' ')}",
        "pose": f"body pose only: {label.replace('_', ' ')}",
    }.get(kind, "tiny pose/expression variation only")
    return f"""Character reference pack image.
STRICT CHARACTER IDENTITY REFERENCE GENERATION.

Book: {title}
Character: {character_name}
Task: {task}

HARD IDENTITY LOCK - COPY THIS CHARACTER, DO NOT REDESIGN:
{design_lock}

NON-NEGOTIABLE RULES:
- Use the provided reference image as the visual source of truth.
- Keep identity, proportions, silhouette, colors, outfit, helmet/head shape, face layout, markings, materials, and costume construction unchanged.
- Allowed change: {allowed_change}.
- Generate exactly one isolated character only.
- Transparent background PNG cutout with real alpha.
- Bright, even, soft frontal lighting; the full face clearly and evenly lit and fully visible. No dark or black face, no face lost in shadow, no heavy/dramatic low-key lighting, no dark backdrop bleeding onto the face, no shadow or dark mask obscuring the face.
- Full body visible, centered, uncropped, readable limbs, clean production layer.
- No alternate costume, no alternate helmet, no alternate armor, no changed species, no changed age/body type, no new props unless already part of the locked design.
- No text, letters, captions, labels, logos, watermarks, UI, panels, grids, background scenes, extra characters, duplicate characters, or model-sheet collage.
- If any instruction conflicts with identity preservation, identity preservation wins.
{identity_lock}
Reference notes from planner:
{reference_notes or "No external reference notes provided."}

Objects/items to preserve in this book when relevant, but do not add unless the task asks for them:
{focus_items or "none"}

Style:
{style}
Polished dimensional storybook/comic character art, clean readable silhouette, production-ready transparent layer.
"""


def _character_negative_prompt() -> str:
    return (
        "text, letters, captions, labels, logo, watermark, signature, UI, grid, gridlines, checkerboard, comic panel, "
        "white background, paper, studio backdrop, extra character, duplicate character, crowd, background scene, cropped body, missing limbs, extra limbs, "
        "dark face, black face, face in shadow, shadowed face, heavy shadows, harsh shadows, low-key lighting, dramatic lighting, dark background, black background, silhouette, underexposed, "
        "broken hands, distorted face, inconsistent outfit, alternate outfit, redesigned costume, changed helmet, changed head shape, changed body type, changed species, "
        "tail unless explicitly part of the character, "
        "weapons, scary imagery, gore, flat vector sticker"
    )


def _book_characters(book: dict[str, Any], pages: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    brief = book.get("planner_brief") or {}
    names.extend(str(item).strip() for item in brief.get("focus_characters") or [])
    for page in pages:
        names.extend(str(item).strip() for item in page.get("characters") or [])
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(name)
    return result


def _character_design_lock(
    project_root: Path,
    slug: str,
    character_name: str,
    book: dict[str, Any],
    pack_root: Path,
) -> str:
    design_lock_path = pack_root / "design_lock.md"
    if design_lock_path.exists():
        return design_lock_path.read_text(encoding="utf-8").strip()
    brief = book.get("planner_brief") or {}
    locks = brief.get("character_design_locks") or {}
    if isinstance(locks, dict):
        for key in (character_name, slug, character_name.lower(), slug.replace("_", " ")):
            value = str(locks.get(key) or "").strip()
            if value:
                design_lock_path.write_text(value.rstrip() + "\n", encoding="utf-8")
                return value
    notes = str(brief.get("reference_notes") or "").strip()
    fallback = (
        f"{character_name} is one exact recurring character, not a generic archetype. "
        "If an approved front reference exists, match that reference as the source of truth. "
        "Preserve the same head/helmet outline, face layout, body proportions, costume silhouette, material finish, "
        "color placement, markings, and recognizable props or motifs. "
        "Only pose, camera angle, and expression may change. "
        "Do not redesign the character, change species/body type, swap outfits, simplify details, add new limbs, or create a different character with the same name."
    )
    if notes:
        fallback = f"{fallback}\nAdditional project notes: {notes}"
    design_lock_path.write_text(fallback.rstrip() + "\n", encoding="utf-8")
    return fallback


def _identity_reference_path(pack_root: Path, references_dir: Path, slug: str) -> Path | None:
    candidates = [
        pack_root / "identity" / f"{slug}_identity_reference.png",
        pack_root / "identity" / "identity_reference.png",
        pack_root / "identity" / f"{slug}_front_reference.png",
        references_dir / f"{slug}_turnaround_front.png",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _reference_image_count(value: int | None) -> int:
    if value is None:
        return DEFAULT_REFERENCE_IMAGE_COUNT
    return max(1, min(MAX_REFERENCE_IMAGE_COUNT, int(value or DEFAULT_REFERENCE_IMAGE_COUNT)))


def _reference_tasks(
    slug: str,
    references_dir: Path,
    expressions_dir: Path,
    poses_dir: Path,
    samples_dir: Path,
    requested_count: int,
) -> list[tuple[str, str, Path]]:
    core = [
        *[("turnaround", view, references_dir / f"{slug}_turnaround_{view}.png") for view in TURNAROUND_VIEWS],
        *[("expression", expression, expressions_dir / f"{slug}_expression_{expression}.png") for expression in EXPRESSIONS],
        *[("pose", pose, poses_dir / f"{slug}_pose_{pose}.png") for pose in POSES],
    ]
    if requested_count <= len(core):
        return core[:requested_count]

    extra_count = requested_count - len(core)
    extras = [
        ("sample", f"variant_{index:03d}", samples_dir / f"{slug}_sample_variant_{index:03d}.png")
        for index in range(1, extra_count + 1)
    ]
    return core + extras


def _load_book(project_root: Path, book_slug: str) -> dict[str, Any]:
    path = project_root / "books" / book_slug / "book.yaml"
    if not path.exists():
        return {"slug": book_slug, "title": book_slug}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {"slug": book_slug, "title": book_slug}


def _load_pages(project_root: Path, book_slug: str) -> list[dict[str, Any]]:
    pages_dir = project_root / "books" / book_slug / "pages"
    pages: list[dict[str, Any]] = []
    for path in sorted(pages_dir.glob("page_*.yaml")):
        pages.append(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    return pages


def _qa_image(path: Path) -> dict[str, Any]:
    notes: list[str] = []
    min_pixels = int(os.getenv("HACKSTER_CHARACTER_MIN_PIXELS", "768"))
    min_transparent_ratio = float(os.getenv("HACKSTER_CHARACTER_MIN_TRANSPARENT_RATIO", "0.05"))
    try:
        with Image.open(path) as image:
            width, height = image.size
            if width < min_pixels or height < min_pixels:
                notes.append(f"image is smaller than {min_pixels}px on one side")
            rgba = image.convert("RGBA")
            alpha = rgba.getchannel("A")
            alpha_low, alpha_high = alpha.getextrema()
            transparent_pixels = sum(alpha.histogram()[:10])
            transparent_ratio = transparent_pixels / max(1, width * height)
            if alpha_low >= 250:
                notes.append("image has no transparent background alpha")
            elif transparent_ratio < min_transparent_ratio:
                notes.append(f"transparent background area is below {min_transparent_ratio:.0%}")
            stat = ImageStat.Stat(image.convert("RGB"))
            if max(sum(channel) for channel in stat.extrema) == 0:
                notes.append("image appears fully black")
            if all(abs(high - low) < 2 for low, high in stat.extrema):
                notes.append("image appears blank or flat")
            return {
                "pass": not notes,
                "width": width,
                "height": height,
                "alpha_min": alpha_low,
                "alpha_max": alpha_high,
                "transparent_ratio": round(transparent_ratio, 4),
                "notes": notes,
            }
    except Exception as exc:
        return {"pass": False, "width": 0, "height": 0, "notes": [str(exc)]}


def _pack_ready(pack: CharacterReferencePackResult, *, requested_count: int | None = None) -> bool:
    passing = [item for item in pack.items if item.qa.get("pass")]
    turnarounds = len([item for item in passing if item.kind == "turnaround"])
    expressions = len([item for item in passing if item.kind == "expression"])
    poses = len([item for item in passing if item.kind == "pose"])
    target = _reference_image_count(requested_count)
    if pack.errors or len(passing) < target:
        return False
    if target < DEFAULT_REFERENCE_IMAGE_COUNT:
        return True
    return turnarounds >= len(TURNAROUND_VIEWS) and expressions >= MIN_EXPRESSIONS and poses >= MIN_POSES


def _write_manifest(
    book_slug: str,
    book: dict[str, Any],
    pack: CharacterReferencePackResult,
    *,
    requested_count: int | None = None,
) -> None:
    payload = {
        "schema_version": 1,
        "book_slug": book_slug,
        "book_title": book.get("title"),
        "character": pack.name,
        "character_slug": pack.slug,
        "status": "ready" if pack.ready else "needs_review",
        "requested_image_count": _reference_image_count(requested_count),
        "image_count": len(pack.items),
        "generated_count": pack.generated_count,
        "skipped_count": pack.skipped_count,
        "updated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "reference_mode": os.getenv("HACKSTER_CHARACTER_REFERENCE_MODE", "flux_reference_pack"),
        "reference_workflow": os.getenv("COMFYUI_CHARACTER_REFERENCE_WORKFLOW_PATH", ""),
        "reference_workflow_kind": os.getenv("COMFYUI_CHARACTER_REFERENCE_WORKFLOW_KIND", "flux_pulid"),
        "reference_weight": os.getenv("COMFYUI_CHARACTER_REFERENCE_WEIGHT", os.getenv("COMFYUI_PULID_WEIGHT", "0.75")),
        "character_workflow": os.getenv("COMFYUI_CHARACTER_WORKFLOW_PATH", ""),
        "reference_conditioning_configured": _reference_conditioning_configured(),
        "reference_conditioning_warning": "" if _reference_conditioning_configured() else (
            "No FLUX Redux/Kontext/PuLID/IP-Adapter reference workflow is configured; generated images rely mostly on text prompts and may drift."
        ),
        "design_lock_path": (pack.root / "design_lock.md").as_posix(),
        "future_lora": {
            "recommended": True,
            "minimum_curated_images": 20,
            "target_curated_images": 40,
            "status": "not_trained",
        },
        "files": [item.__dict__ for item in pack.items],
        "errors": pack.errors,
    }
    pack.manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_qa_report(pack: CharacterReferencePackResult) -> None:
    path = pack.root / "qa" / "character_reference_qa.md"
    rows = [
        "| Kind | Label | Status | Size | Notes |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in pack.items:
        qa = item.qa or {}
        notes = "; ".join(str(note).replace("|", "/") for note in qa.get("notes", [])) or item.error or ""
        rows.append(f"| {item.kind} | {item.label} | {item.status} | {qa.get('width', 0)}x{qa.get('height', 0)} | {notes} |")
    text = f"# Character Reference QA: {pack.name}\n\nReady: {pack.ready}\n\n" + "\n".join(rows) + "\n"
    path.write_text(text, encoding="utf-8")


def _item(
    kind: str,
    label: str,
    image_path: Path,
    prompt_path: Path,
    status: str,
    *,
    qa: dict[str, Any] | None = None,
    error: str = "",
) -> CharacterReferenceItem:
    return CharacterReferenceItem(
        kind=kind,
        label=label,
        path=image_path.as_posix(),
        prompt_path=prompt_path.as_posix(),
        status=status,
        qa=qa or {},
        error=error,
    )


def _emit(progress_callback: Callable[[str, dict[str, Any]], None] | None, event: str, **payload: Any) -> None:
    if progress_callback:
        progress_callback(event, payload)


@contextmanager
def _temporary_environ(values: dict[str, str]) -> Iterator[None]:
    previous: dict[str, str | None] = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
