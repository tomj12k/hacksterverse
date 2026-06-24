"""REST API router — all /api/* endpoints for the Story Maker."""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import urllib.error
import urllib.request

from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, Body, HTTPException
from pydantic import BaseModel, Field

from .jobutil import evict_oldest
from .automation.comfyui_engine import generate_image_comfyui, request_bytes
from .automation.transparent_png import make_background_transparent
from .config import GENERATED_PAGES_DIR, LAYERS_DIR, PROJECT_ROOT
from .services.assets import list_assets, list_poses
from .services.character_training import active_lora_for_character, character_slug_from_output_path, lora_environment_for_character
from .services.exporter import export_scene
from .services.story_maker import (
    apply_text_style_to_all_pages,
    book_illustration_path,
    book_readiness,
    load_scene,
    niko_pose_from_rig,
    remove_hackster_niko_from_book,
    save_scene,
    set_scene_status,
    validate_scene,
)
from .services.text_art import render_text_art
from .automation.niko_lock import render_niko_pose

log = logging.getLogger(__name__)

_ENV_FILE = Path(__file__).parent.parent / ".env"
load_dotenv(_ENV_FILE)

router = APIRouter()


class StatusRequest(BaseModel):
    status: str
    approved_by: str | None = None
    notes: str = ""


class ApplyTextStyleRequest(BaseModel):
    layer_id: str = "page_text"


# ── Scenes ────────────────────────────────────────────────────────────────────


@router.get("/scenes/{book_slug}/{page_number}")
def get_scene(book_slug: str, page_number: int) -> dict[str, Any]:
    try:
        return load_scene(book_slug, page_number)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/scenes/{book_slug}/{page_number}", status_code=204)
def put_scene(
    book_slug: str,
    page_number: int,
    scene: dict[str, Any] = Body(...),
) -> None:
    if scene.get("book_slug") != book_slug or scene.get("page_number") != page_number:
        raise HTTPException(
            status_code=422, detail="book_slug/page_number mismatch with URL"
        )
    if "layers" not in scene:
        raise HTTPException(status_code=422, detail="layers field is required")
    try:
        save_scene(scene)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/scenes/{book_slug}/{page_number}/qa")
def get_scene_qa(book_slug: str, page_number: int) -> dict[str, Any]:
    try:
        scene = load_scene(book_slug, page_number)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return validate_scene(scene)


@router.put("/scenes/{book_slug}/{page_number}/status")
def put_scene_status(
    book_slug: str,
    page_number: int,
    request: StatusRequest,
) -> dict[str, Any]:
    try:
        scene = set_scene_status(
            book_slug,
            page_number,
            request.status,
            approved_by=request.approved_by,
            notes=request.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "status": scene["status"],
        "approval": scene.get("approval", {}),
        "qa": scene.get("qa", validate_scene(scene)),
    }


@router.get("/books/{book_slug}/readiness")
def get_book_readiness(book_slug: str) -> dict[str, Any]:
    try:
        return book_readiness(book_slug)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/scenes/{book_slug}/{page_number}/text-style/apply-all")
def post_apply_text_style_all(
    book_slug: str,
    page_number: int,
    request: ApplyTextStyleRequest,
) -> dict[str, Any]:
    try:
        return apply_text_style_to_all_pages(
            book_slug,
            page_number,
            layer_id=request.layer_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/books/{book_slug}/remove-hackster-niko")
def post_remove_hackster_niko_from_book(book_slug: str) -> dict[str, Any]:
    try:
        return remove_hackster_niko_from_book(book_slug)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ── Assets ────────────────────────────────────────────────────────────────────


@router.get("/assets")
def get_assets() -> dict[str, Any]:
    return list_assets()


@router.get("/assets/characters/{character_slug}/poses")
def get_character_poses(character_slug: str) -> list[dict[str, Any]]:
    return list_poses(character_slug)


# ── Generation Jobs ───────────────────────────────────────────────────────────


@dataclass
class _JobStatus:
    status: str = "pending"  # pending | running | done | failed
    asset_path: str | None = None
    prompt: str = ""
    error: str = ""


# Module-level job store. Ephemeral — lost on server restart.
_jobs: dict[str, _JobStatus] = {}


class GenerateRequest(BaseModel):
    layer_id: str
    layer_type: str
    prompt: str
    output_path: str
    lighting_variant: str


class TextArtRequest(BaseModel):
    text: str
    output_path: str
    width_px: int = 1800
    height_px: int = 520
    dpi: int = 300
    style: dict[str, Any] = Field(default_factory=dict)


class NikoPoseRequest(BaseModel):
    pose: str = "custom"
    output_path: str
    rig: dict[str, Any] = Field(default_factory=dict)


@router.get("/generate/connection")
def get_generate_connection() -> dict[str, Any]:
    load_dotenv(_ENV_FILE)
    base_url = (os.getenv("COMFYUI_URL") or "http://127.0.0.1:8188").rstrip("/")
    try:
        request_bytes(f"{base_url}/system_stats")
        return {"ok": True, "url": base_url, "error": None}
    except (RuntimeError, urllib.error.URLError, OSError) as exc:
        return {"ok": False, "url": base_url, "error": str(exc)}


@router.get("/generate/jobs")
def list_generate_jobs() -> dict[str, Any]:
    return {
        "jobs": [
            {
                "job_id": jid,
                "status": j.status,
                "asset_path": j.asset_path,
                "prompt": j.prompt,
                "error": j.error,
            }
            for jid, j in reversed(list(_jobs.items()))
        ]
    }


@router.post("/generate")
def post_generate(
    request: GenerateRequest, background_tasks: BackgroundTasks
) -> dict[str, str]:
    _resolve_generation_output_path(request.output_path)
    job_id = str(uuid.uuid4())
    _jobs[job_id] = _JobStatus(status="pending", prompt=request.prompt)
    evict_oldest(_jobs)
    background_tasks.add_task(_run_generation, job_id, request)
    return {"job_id": job_id}


@router.get("/generate/{job_id}")
def get_generate_status(job_id: str) -> dict[str, Any]:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    return {"status": job.status, "asset_path": job.asset_path, "prompt": job.prompt, "error": job.error}


def _run_generation(job_id: str, request: GenerateRequest) -> None:
    if job_id not in _jobs:
        # Evicted before the background task ran (store at capacity) — nothing
        # left to update.
        return
    _jobs[job_id].status = "running"
    try:
        output = _resolve_generation_output_path(request.output_path)
        character_slug = character_slug_from_output_path(request.output_path)
        prompt = request.prompt
        active_lora = active_lora_for_character(character_slug or "") if character_slug else {}
        trigger = active_lora.get("trigger", "").strip()
        if trigger and trigger.lower() not in prompt.lower():
            prompt = f"{trigger}, {prompt}"
        with lora_environment_for_character(character_slug):
            generate_image_comfyui(prompt, output)
        if character_slug and output.exists():
            make_background_transparent(output)
        _jobs[job_id].status = "done"
        _jobs[job_id].asset_path = output.relative_to(PROJECT_ROOT).as_posix()
    except Exception as exc:
        # Broad catch is intentional: generate_image_comfyui can raise
        # urllib.error.URLError, json.JSONDecodeError, PIL errors, IOError,
        # or TimeoutError — we need to surface all of them as job failures.
        log.exception("Generation job %s failed", job_id)
        _jobs[job_id].status = "failed"
        _jobs[job_id].error = str(exc)


def _resolve_generation_output_path(output_path: str) -> Path:
    rel_path = Path(output_path)
    if rel_path.is_absolute() or not output_path.strip():
        raise HTTPException(status_code=422, detail="output_path must be a relative PNG path")
    if rel_path.suffix.lower() != ".png":
        raise HTTPException(status_code=422, detail="output_path must end in .png")

    target = (PROJECT_ROOT / rel_path).resolve()
    allowed_roots = {LAYERS_DIR.resolve(), GENERATED_PAGES_DIR.resolve()}
    if not any(root in target.parents for root in allowed_roots):
        raise HTTPException(
            status_code=422,
            detail="output_path must be inside assets/layers or data/generated/pages",
        )
    return target


@router.post("/generate/text-art")
def post_generate_text_art(request: TextArtRequest) -> dict[str, str]:
    output = _resolve_text_art_output_path(request.output_path)
    render_text_art(
        request.text,
        output,
        width_px=request.width_px,
        height_px=request.height_px,
        dpi=request.dpi,
        style=request.style,
    )
    return {"asset_path": output.relative_to(PROJECT_ROOT).as_posix()}


def _resolve_text_art_output_path(output_path: str) -> Path:
    rel_path = Path(output_path)
    if rel_path.is_absolute() or not output_path.strip():
        raise HTTPException(status_code=422, detail="output_path must be a relative PNG path")
    if rel_path.suffix.lower() != ".png":
        raise HTTPException(status_code=422, detail="output_path must end in .png")

    target = (PROJECT_ROOT / rel_path).resolve()
    text_root = (LAYERS_DIR / "text").resolve()
    if target != text_root and text_root not in target.parents:
        raise HTTPException(
            status_code=422,
            detail="text art output_path must be inside assets/layers/text",
        )
    return target


@router.post("/generate/niko-pose")
def post_generate_niko_pose(request: NikoPoseRequest) -> dict[str, str]:
    output = _resolve_niko_pose_output_path(request.output_path)
    pose = niko_pose_from_rig(request.pose, "Custom Niko Pose", request.rig)
    render_niko_pose(output, pose)
    return {"asset_path": output.relative_to(PROJECT_ROOT).as_posix()}


def _resolve_niko_pose_output_path(output_path: str) -> Path:
    rel_path = Path(output_path)
    if rel_path.is_absolute() or not output_path.strip():
        raise HTTPException(status_code=422, detail="output_path must be a relative PNG path")
    if rel_path.suffix.lower() != ".png":
        raise HTTPException(status_code=422, detail="output_path must end in .png")

    target = (PROJECT_ROOT / rel_path).resolve()
    niko_root = (LAYERS_DIR / "characters" / "niko").resolve()
    if target != niko_root and niko_root not in target.parents:
        raise HTTPException(
            status_code=422,
            detail="Niko pose output_path must be inside assets/layers/characters/niko",
        )
    return target


# ── Generated image management ───────────────────────────────────────────────


@router.delete("/generated/pages/{filename}", status_code=204)
def delete_generated_image(filename: str) -> None:
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=422, detail="Invalid filename")
    if not filename.lower().endswith(".png"):
        raise HTTPException(status_code=422, detail="Only .png files can be deleted")
    target = GENERATED_PAGES_DIR / filename
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    target.unlink()


# ── Export ────────────────────────────────────────────────────────────────────


@router.post("/export/{book_slug}/{page_number}")
def post_export(
    book_slug: str,
    page_number: int,
    mode: str = "flat",
) -> dict[str, str]:
    if mode not in ("flat", "draft"):
        raise HTTPException(status_code=422, detail="mode must be 'flat' or 'draft'")
    try:
        scene = load_scene(book_slug, page_number)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    out_path = export_scene(scene, mode=mode)
    try:
        rel = out_path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        rel = out_path.as_posix()
    return {"output_path": rel}


@router.post("/promote/{book_slug}/{page_number}")
def post_promote(
    book_slug: str,
    page_number: int,
    mode: str = "flat",
) -> dict[str, str]:
    if mode not in ("flat", "draft"):
        raise HTTPException(status_code=422, detail="mode must be 'flat' or 'draft'")
    try:
        scene = load_scene(book_slug, page_number)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    exported_path = export_scene(scene, mode=mode)
    promoted_path = book_illustration_path(book_slug, page_number)
    promoted_path.parent.mkdir(parents=True, exist_ok=True)
    promoted_path.write_bytes(exported_path.read_bytes())

    return {
        "output_path": exported_path.relative_to(PROJECT_ROOT).as_posix(),
        "promoted_path": promoted_path.relative_to(PROJECT_ROOT).as_posix(),
    }
