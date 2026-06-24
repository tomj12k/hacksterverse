"""Book-generation job data model and execution infrastructure.

Holds the job record type, the in-memory live-job store (+ its lock), the
bounded worker pool, and the payload serializer. The orchestration that drives
these (the ``_run_*`` functions) currently lives in ``main.py``; keeping the
data model and pool here gives that code a stable, dependency-free home and
lets other modules reference job state without importing ``main``.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session

from .automation.build_book import build_book
from .automation.character_reference import (
    DEFAULT_REFERENCE_IMAGE_COUNT,
    MAX_REFERENCE_IMAGE_COUNT,
    generate_character_reference_packs,
)
from .automation.pipeline import BuildOptions
from .config import PROJECT_ROOT
from .database import engine
from .job_store import persist_job
from .jobutil import evict_oldest
from .page_ops import page_for_book, refresh_scene_image_from_page
from .services.artifacts import book_artifact_counts, first_missing_image_page
from .services.books import (
    generate_book_from_dgx_brief,
    get_book_by_slug,
    get_pages_for_book,
)
from .services.exports import export_page_spec_yaml, export_page_specs_yaml
from .services.prompts import generate_page_prompt, generate_prompts_for_book
from .services.story_maker import book_page_count, prepare_book_review_scenes


@dataclass
class BookGenerationJob:
    job_id: str
    book_slug: str
    redirect_url: str
    status: str = "queued"
    stage: str = "queued"
    progress: int = 3
    events: list[str] = field(default_factory=list)
    error: str = ""
    result: dict[str, Any] = field(default_factory=dict)


# Live jobs, keyed by job_id. Bounded at insertion via jobutil.evict_oldest.
book_generation_jobs: dict[str, BookGenerationJob] = {}
book_generation_jobs_lock = threading.Lock()

# Bounded pool for long-running generation jobs. Workers are non-daemon, so the
# interpreter joins them at exit (an in-flight write finishes instead of being
# killed mid-file); concurrency is capped so parallel runs cannot exhaust the
# single GPU/host.
book_generation_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="book-gen")


def book_generation_job_payload(job: BookGenerationJob) -> dict[str, Any]:
    """Serialize a job record to the JSON-friendly shape the API returns."""
    return {
        "job_id": job.job_id,
        "book_slug": job.book_slug,
        "redirect_url": job.redirect_url,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "events": list(job.events),
        "error": job.error,
        "result": dict(job.result),
    }


def assert_full_book_generation_complete(book_slug: str) -> dict[str, Any]:
    """Verify every expected artifact exists; raise RuntimeError if not."""
    expected_pages = max(1, book_page_count(book_slug))
    counts = book_artifact_counts(book_slug, expected_pages)
    root = PROJECT_ROOT / "books" / book_slug
    production_pdf = root / "exports" / "lulu" / f"{book_slug}_interior_lulu_print.pdf"
    idml = root / "exports" / "affinity" / f"{book_slug}_affinity_starter.idml"
    audit: dict[str, Any] = {
        **counts,
        "production_pdf": production_pdf.as_posix(),
        "production_pdf_exists": production_pdf.exists(),
        "idml": idml.as_posix(),
        "idml_exists": idml.exists(),
    }
    missing: list[str] = []
    for key, label in (
        ("pages", "planned page YAML files"),
        ("book_prompts", "book prompt files"),
        ("page_specs", "page spec YAML files"),
        ("images", "page images"),
        ("reviews", "review files"),
    ):
        if int(counts[key]) < expected_pages:
            missing.append(f"{label}: {counts[key]}/{expected_pages}")
    if not production_pdf.exists():
        missing.append("Lulu production PDF")
    if not idml.exists():
        missing.append("Affinity IDML package")
    audit["missing"] = missing
    if missing:
        raise RuntimeError("Final artifact check failed: " + "; ".join(missing))
    return audit


def assert_page_image_generation_complete(book_slug: str, page_number: int) -> dict[str, Any]:
    """Verify a single page's illustration exists; raise RuntimeError if not."""
    image_path = PROJECT_ROOT / "books" / book_slug / "illustrations" / f"page_{page_number:03d}.png"
    audit = {
        "page_number": page_number,
        "image": image_path.as_posix(),
        "image_exists": image_path.exists(),
    }
    if not image_path.exists():
        raise RuntimeError(f"Final page image check failed: page {page_number:03d} image was not created.")
    return audit


def artifact_audit_message(audit: dict[str, Any]) -> str:
    """Human-readable summary line for a completed full-book artifact audit."""
    expected = int(audit.get("expected_pages") or 0)
    if "images" in audit:
        return (
            "Final artifact check passed: "
            f"{audit.get('images', 0)}/{expected} images, "
            f"{audit.get('reviews', 0)}/{expected} review files, Lulu PDF, and Affinity IDML are present."
        )
    return "Final artifact check passed."


def generate_single_character_pack(
    name: str,
    slug: str,
    *,
    force: bool = False,
    image_count: int | None = None,
    progress_callback: Any | None = None,
) -> Any:
    """Generate a standalone reusable reference pack for one character."""
    return generate_character_reference_packs(
        book_slug="character_library",
        book={
            "title": "Character Library",
            "slug": "character_library",
            "global_illustration_style": (
                "premium dimensional children's picture book illustration, friendly expressive design, "
                "saturated colors, soft cinematic lighting"
            ),
            "planner_brief": {
                "focus_characters": [name],
                "focus_items": [],
                "reference_notes": f"Build a consistent reusable reference pack for {name}.",
            },
        },
        pages=[],
        force=force,
        image_count_per_character=image_count,
        manage_dgx_image_profile=True,
        progress_callback=progress_callback,
    )


def reference_pack_image_count(value: object) -> int:
    """Clamp a requested per-character image count to the supported range."""
    try:
        count = int(str(value or DEFAULT_REFERENCE_IMAGE_COUNT))
    except (TypeError, ValueError):
        count = DEFAULT_REFERENCE_IMAGE_COUNT
    return max(1, min(MAX_REFERENCE_IMAGE_COUNT, count))


# Underscore aliases let the relocated orchestration (below) reference the
# module's public names without edits.
_book_generation_jobs = book_generation_jobs
_book_generation_jobs_lock = book_generation_jobs_lock
_book_generation_executor = book_generation_executor
_book_generation_job_payload = book_generation_job_payload
_book_artifact_counts = book_artifact_counts
_first_missing_image_page = first_missing_image_page
_page_for_book = page_for_book
_refresh_scene_image_from_page = refresh_scene_image_from_page
_assert_full_book_generation_complete = assert_full_book_generation_complete
_assert_page_image_generation_complete = assert_page_image_generation_complete
_artifact_audit_message = artifact_audit_message
_generate_single_character_pack = generate_single_character_pack
_reference_pack_image_count = reference_pack_image_count


def _record_book_generation_job(job_id: str, *, stage: str, message: str, progress: int | None = None, status: str | None = None, **result: Any) -> None:
    with _book_generation_jobs_lock:
        job = _book_generation_jobs[job_id]
        job.stage = stage
        if status:
            job.status = status
        if progress is not None:
            job.progress = max(job.progress, min(100, int(progress)))
        if result:
            job.result.update(result)
        job.events.append(message)
        job.events = job.events[-120:]
        snapshot = _book_generation_job_payload(job)
    # Write-through to SQLite outside the lock so DB I/O never blocks other
    # jobs' progress updates.
    persist_job(snapshot)


def _progress_to_job(job_id: str, event: str, payload: dict[str, Any]) -> None:
    message = str(payload.get("message") or event.replace("_", " ").title())
    if event == "dgx_starting":
        _record_book_generation_job(job_id, stage="dgx_starting", message=message, progress=8, status="running")
    elif event == "planner_request_submitted":
        _record_book_generation_job(
            job_id,
            stage="planner_generating",
            message=message,
            progress=14,
            status="running",
            request_summary=payload.get("request_summary", {}),
        )
    elif event == "planner_response_received":
        _record_book_generation_job(
            job_id,
            stage="story_received",
            message=f"{message} ({payload.get('pages', 0)} pages in response.)",
            progress=22,
            status="running",
            response_pages=payload.get("pages", 0),
            response_title=payload.get("title", ""),
            response_summary=payload.get("response_summary", {}),
        )
    elif event == "planner_page_saved":
        page_number = int(payload.get("page_number") or payload.get("pages_saved") or 1)
        pages_total = max(1, int(payload.get("pages_total") or 1))
        planner_progress = 14 + (page_number / pages_total) * 12
        _record_book_generation_job(
            job_id,
            stage="planner_page_saved",
            message=f"{message} ({page_number}/{pages_total})",
            progress=round(planner_progress),
            status="running",
            pages_created=payload.get("pages_saved", page_number),
            response_summary=payload.get("response_summary", {}),
        )
    elif event == "pages_created":
        _record_book_generation_job(
            job_id,
            stage="pages_created",
            message=f"{message} ({payload.get('pages', 0)} pages created.)",
            progress=28,
            status="running",
            pages_created=payload.get("pages", 0),
        )
    elif event == "dgx_releasing":
        _record_book_generation_job(job_id, stage="planner_releasing", message=message, progress=24, status="running")
    else:
        _record_book_generation_job(job_id, stage="running", message=message, progress=12, status="running")


def _pipeline_progress_to_job(job_id: str, event: str, payload: dict[str, Any]) -> None:
    message = str(payload.get("message") or event.replace("_", " ").title())
    if event in {"build_started", "prompts_started"}:
        _record_book_generation_job(job_id, stage="managed_build_started", message=message, progress=32, status="running")
    elif event in {"characters_started", "character_reference_started", "character_reference_done", "character_reference_skipped", "character_reference_failed"}:
        character_index = int(payload.get("character_index") or 1)
        total_characters = max(1, int(payload.get("total_characters") or payload.get("characters") or 1))
        item_index = int(payload.get("item_index") or 1)
        total_items = max(1, int(payload.get("total_items") or 1))
        unit_progress = ((character_index - 1) + (item_index / total_items)) / total_characters
        _record_book_generation_job(
            job_id,
            stage="characters_generating",
            message=message,
            progress=round(36 + unit_progress * 9),
            status="running",
            characters_done=character_index,
            characters_total=total_characters,
        )
    elif event == "characters_done":
        _record_book_generation_job(
            job_id,
            stage="characters_complete",
            message=message,
            progress=45,
            status="running",
            character_reference_images=payload.get("images", 0),
            character_reference_errors=payload.get("errors", 0),
        )
    elif event == "prompts_done":
        _record_book_generation_job(
            job_id,
            stage="prompts_created",
            message=message,
            progress=35,
            status="running",
            prompts_created=payload.get("prompts", 0),
        )
    elif event == "images_started":
        _record_book_generation_job(
            job_id,
            stage="images_generating",
            message=(
                f"{message} Planner vLLM may shut down here so FLUX/ComfyUI can reclaim GPU memory."
            ),
            progress=46,
            status="running",
            images_total=payload.get("pages", 0),
        )
    elif event in {"image_page_started", "image_page_done", "image_page_skipped", "image_page_failed"}:
        page_index = int(payload.get("page_index") or 1)
        total_pages = max(1, int(payload.get("total_pages") or 1))
        if event == "image_page_started":
            image_progress = 46 + ((page_index - 1) / total_pages) * 40
        else:
            image_progress = 46 + (page_index / total_pages) * 40
        _record_book_generation_job(
            job_id,
            stage="images_generating",
            message=message,
            progress=round(image_progress),
            status="running",
            images_done=page_index,
            images_total=total_pages,
        )
    elif event == "images_done":
        _record_book_generation_job(
            job_id,
            stage="images_complete",
            message=message,
            progress=87,
            status="running",
            images_created=payload.get("images", 0),
            image_errors=payload.get("errors", 0),
        )
    elif event in {"review_done", "draft_pdf_done"}:
        _record_book_generation_job(job_id, stage="review_exported", message=message, progress=91, status="running")
    elif event in {"production_pdf_done", "idml_done", "affinity_done"}:
        _record_book_generation_job(job_id, stage="production_exports", message=message, progress=96, status="running")
    elif event in {"reports_done", "build_done"}:
        _record_book_generation_job(job_id, stage="production_exports", message=message, progress=98, status="running")
    else:
        _record_book_generation_job(job_id, stage="managed_build_started", message=message, progress=34, status="running")


def start_book_generation_job(book_slug: str, payload: dict[str, Any]) -> BookGenerationJob:
    job_id = str(uuid.uuid4())
    redirect_url = str(payload.get("redirect_url") or f"/workflow?book_slug={book_slug}")
    job = BookGenerationJob(job_id=job_id, book_slug=book_slug, redirect_url=redirect_url)
    with _book_generation_jobs_lock:
        _book_generation_jobs[job_id] = job
        evict_oldest(_book_generation_jobs)
    _record_book_generation_job(job_id, stage="queued", message="Request accepted by Hackster Studio.", progress=4, status="queued")
    _book_generation_executor.submit(_run_book_generation_job, job_id, book_slug, payload)
    return job


def _run_book_generation_job(job_id: str, book_slug: str, payload: dict[str, Any]) -> None:
    try:
        run_mode = str(payload.get("run_mode") or "full")
        if run_mode == "resume":
            _run_resume_generation_job(job_id, book_slug)
            return
        if run_mode == "page_image":
            _run_page_image_generation_job(job_id, book_slug, int(payload.get("page_number") or 1))
            return
        if run_mode == "characters":
            _run_character_reference_job(job_id, book_slug, force=bool(payload.get("force")))
            return
        if run_mode == "single_character_reference":
            _run_single_character_reference_job(
                job_id,
                name=str(payload.get("character_name") or ""),
                slug=str(payload.get("character_slug") or ""),
                force=bool(payload.get("force")),
                image_count=_reference_pack_image_count(payload.get("image_count")),
                redirect_url=str(payload.get("redirect_url") or ""),
            )
            return
        with Session(engine) as job_session:
            _record_book_generation_job(job_id, stage="dgx_starting", message="Preparing DGX planner for this request.", progress=10, status="running")
            pages = generate_book_from_dgx_brief(
                job_session,
                book_slug,
                idea=str(payload.get("idea", "")),
                characters=str(payload.get("characters", "")),
                objects=str(payload.get("objects", "")),
                character_count=int(payload.get("character_count") or 3),
                object_count=int(payload.get("object_count") or 4),
                reference_notes=str(payload.get("reference_notes", "")),
                progress=lambda event, data: _progress_to_job(job_id, event, data),
            )
            _record_book_generation_job(
                job_id,
                stage="prompts_created",
                message="Generating image prompts for the created pages.",
                progress=30,
                status="running",
                pages_created=len(pages),
            )
            prompt_paths = generate_prompts_for_book(job_session, book_slug)
            _record_book_generation_job(
                job_id,
                stage="specs_exported",
                message=f"Generated {len(prompt_paths)} image prompts.",
                progress=32,
                status="running",
                prompts_created=len(prompt_paths),
            )
            specs = export_page_specs_yaml(job_session, book_slug)
            _record_book_generation_job(
                job_id,
                stage="specs_exported",
                message=f"Exported {len(specs)} page specs. Starting managed image generation.",
                progress=34,
                status="running",
                page_specs=len(specs),
            )
        result = build_book(
            PROJECT_ROOT / "books" / book_slug / "book.yaml",
            BuildOptions(
                generate_images=True,
                image_backend="comfyui",
                build_pdf=True,
                build_production_pdf=True,
                build_idml=True,
                force=False,
                force_images=True,
                generate_character_references=True,
                skip_production_gate=True,
                progress_callback=lambda event, data: _pipeline_progress_to_job(job_id, event, data),
            ),
        )
        if result.errors:
            raise RuntimeError("Managed image generation finished with errors: " + "; ".join(result.errors))
        _record_book_generation_job(
            job_id,
            stage="review_exported",
            message="Preparing editable Story Maker scenes from the generated book package.",
            progress=98,
            status="running",
        )
        scene_result = prepare_book_review_scenes(book_slug, overwrite_text=True)
        artifact_audit = _assert_full_book_generation_complete(book_slug)
        _record_book_generation_job(
            job_id,
            stage="review_exported",
            message=f"Prepared {scene_result['prepared_count']} editable review scenes.",
            progress=99,
            status="running",
            scenes_prepared=scene_result["prepared_count"],
            scenes_images_linked=scene_result["images_linked"],
            scenes_text_layers=scene_result["text_layers_updated"],
        )
        _record_book_generation_job(
            job_id,
            stage="complete",
            message=_artifact_audit_message(artifact_audit),
            progress=100,
            status="done",
            images_created=len(result.images),
            review_files=len(result.review_files),
            draft_pdf=str(result.pdf_path or ""),
            production_pdf=str(result.production_pdf_path or ""),
            idml=str(result.idml_path or ""),
            artifact_audit=artifact_audit,
            workflow_url=f"/workflow?book_slug={book_slug}",
            review_url=f"/story-maker?book_slug={book_slug}&page=1",
            assembly_url=f"/book-assembly?book_slug={book_slug}",
        )
    except Exception as exc:
        with _book_generation_jobs_lock:
            job = _book_generation_jobs[job_id]
            job.status = "failed"
            job.stage = "failed"
            job.error = str(exc)
            job.events.append(f"Generation failed: {exc}")


def _run_resume_generation_job(job_id: str, book_slug: str) -> None:
    with Session(engine) as job_session:
        book = get_book_by_slug(job_session, book_slug)
        if book is None or book.id is None:
            raise ValueError(f"Book not found: {book_slug}")
        pages = get_pages_for_book(job_session, book.id)
        if not pages:
            raise ValueError("No planned pages exist yet. Generate the book layout first, then resume images.")
        expected_pages = book.page_count or len(pages)
        before = _book_artifact_counts(book_slug, expected_pages)
        _record_book_generation_job(
            job_id,
            stage="resume_audit",
            message=(
                "Resume audit: "
                f"pages {before['pages']}/{expected_pages}, "
                f"book prompts {before['book_prompts']}/{expected_pages}, "
                f"page specs {before['page_specs']}/{expected_pages}, "
                f"images {before['images']}/{expected_pages}."
            ),
            progress=24,
            status="running",
            resume_audit=before,
        )
        if before["pages"] < expected_pages:
            raise RuntimeError(
                f"Resume found only {before['pages']} planned pages out of {expected_pages}. "
                "Redo the DGX layout/story step before image generation."
            )
        first_missing = _first_missing_image_page(book_slug, expected_pages)
        _record_book_generation_job(
            job_id,
            stage="prompts_created",
            message="Resume run: redoing prompt and page-spec phase from existing planned pages.",
            progress=30,
            status="running",
        )
        prompt_paths = generate_prompts_for_book(job_session, book_slug)
        specs = export_page_specs_yaml(job_session, book_slug)
        after_prompt = _book_artifact_counts(book_slug, expected_pages)
        _record_book_generation_job(
            job_id,
            stage="specs_exported",
            message=(
                f"Resume run: rebuilt {len(prompt_paths)} database prompts, "
                f"{after_prompt['book_prompts']} book prompts, and {len(specs)} page specs."
            ),
            progress=34,
            status="running",
            prompts_created=len(prompt_paths),
            page_specs=len(specs),
            resume_audit=after_prompt,
        )

    if first_missing is None:
        _record_book_generation_job(
            job_id,
            stage="images_complete",
            message="Resume run: all page images already exist; rebuilding review/export package.",
            progress=87,
            status="running",
            images_total=expected_pages,
        )
        options = BuildOptions(
            generate_images=False,
            image_backend="comfyui",
            build_pdf=True,
            build_production_pdf=True,
            build_idml=True,
            force=False,
            skip_production_gate=True,
            manage_dgx_image_profile=False,
            progress_callback=lambda event, data: _pipeline_progress_to_job(job_id, event, data),
        )
    else:
        _record_book_generation_job(
            job_id,
            stage="images_generating",
            message=f"Resume run: redoing failed/missing image step at page {first_missing:03d}.",
            progress=38,
            status="running",
            images_from=first_missing,
            images_total=expected_pages,
        )
        options = BuildOptions(
            generate_images=True,
            image_backend="comfyui",
            build_pdf=True,
            build_production_pdf=True,
            build_idml=True,
            force=False,
            force_images=False,
            page_from=first_missing,
            skip_production_gate=True,
            manage_dgx_image_profile=False,
            progress_callback=lambda event, data: _pipeline_progress_to_job(job_id, event, data),
        )

    result = build_book(PROJECT_ROOT / "books" / book_slug / "book.yaml", options)
    if result.errors:
        raise RuntimeError("Resume image generation finished with errors: " + "; ".join(result.errors))
    _finish_book_generation_job(job_id, book_slug, result, final_message="Resume generation complete.")


def _run_page_image_generation_job(job_id: str, book_slug: str, page_number: int) -> None:
    with Session(engine) as job_session:
        book = get_book_by_slug(job_session, book_slug)
        if book is None or book.id is None:
            raise ValueError(f"Book not found: {book_slug}")
        page = _page_for_book(job_session, book, page_number)
        _record_book_generation_job(
            job_id,
            stage="prompts_created",
            message=f"Refreshing prompt and page spec for page {page_number:03d}.",
            progress=32,
            status="running",
        )
        generate_page_prompt(job_session, page)
        export_page_spec_yaml(job_session, book_slug, page_number)

    result = build_book(
        PROJECT_ROOT / "books" / book_slug / "book.yaml",
        BuildOptions(
            generate_images=True,
            image_backend="comfyui",
            build_pdf=False,
            build_production_pdf=False,
            build_idml=False,
            force=False,
            force_images=True,
            generate_character_references=False,
            page_from=page_number,
            page_to=page_number,
            skip_production_gate=True,
            manage_dgx_image_profile=False,
            progress_callback=lambda event, data: _pipeline_progress_to_job(job_id, event, data),
        ),
    )
    if result.errors:
        raise RuntimeError("Page image regeneration failed: " + "; ".join(result.errors))
    image_version = _refresh_scene_image_from_page(book_slug, page_number)
    artifact_audit = _assert_page_image_generation_complete(book_slug, page_number)
    refresh_token = image_version or uuid.uuid4().hex
    review_url = f"/story-maker?book_slug={book_slug}&page={page_number}&refresh={refresh_token}"
    _record_book_generation_job(
        job_id,
        stage="complete",
        message=f"Page {page_number:03d} image regenerated and verified.",
        progress=100,
        status="done",
        images_created=len(result.images),
        artifact_audit=artifact_audit,
        review_url=review_url,
        page_number=page_number,
        image_version=image_version,
        workflow_url=f"/workflow?book_slug={book_slug}",
    )


def _run_character_reference_job(job_id: str, book_slug: str, *, force: bool = False) -> None:
    _record_book_generation_job(
        job_id,
        stage="characters_generating",
        message="Generating character reference packs before page image generation.",
        progress=36,
        status="running",
    )
    result = generate_character_reference_packs(
        book_slug=book_slug,
        force=force,
        manage_dgx_image_profile=True,
        progress_callback=lambda event, data: _pipeline_progress_to_job(job_id, event, data),
    )
    if not result.ready:
        raise RuntimeError("Character reference gate failed: " + ("; ".join(result.errors) or "QA did not pass"))
    _record_book_generation_job(
        job_id,
        stage="complete",
        message=f"Character reference gate passed for {result.character_count} characters.",
        progress=100,
        status="done",
        character_reference_images=result.image_count,
        workflow_url=f"/workflow?book_slug={book_slug}",
        review_url=f"/story-maker?book_slug={book_slug}&page=1",
    )


def _run_single_character_reference_job(
    job_id: str,
    *,
    name: str,
    slug: str,
    force: bool = False,
    image_count: int = DEFAULT_REFERENCE_IMAGE_COUNT,
    redirect_url: str = "",
) -> None:
    if not name or not slug:
        raise ValueError("Character name and slug are required for reference-pack generation.")
    _record_book_generation_job(
        job_id,
        stage="characters_generating",
        message=f"Generating reference pack for {name}.",
        progress=36,
        status="running",
    )
    result = _generate_single_character_pack(
        name,
        slug,
        force=force,
        image_count=image_count,
        progress_callback=lambda event, data: _pipeline_progress_to_job(job_id, event, data),
    )
    if not result.ready:
        raise RuntimeError("Character reference gate failed: " + ("; ".join(result.errors) or "QA did not pass"))
    _record_book_generation_job(
        job_id,
        stage="complete",
        message=f"Reference pack complete for {name}: {result.image_count} images ready for review.",
        progress=100,
        status="done",
        character_reference_images=result.image_count,
        review_url=redirect_url,
        workflow_url=redirect_url,
    )


def _finish_book_generation_job(job_id: str, book_slug: str, result: Any, *, final_message: str) -> None:
    _record_book_generation_job(
        job_id,
        stage="review_exported",
        message="Preparing editable Story Maker scenes from the generated book package.",
        progress=98,
        status="running",
    )
    scene_result = prepare_book_review_scenes(book_slug, overwrite_text=True)
    artifact_audit = _assert_full_book_generation_complete(book_slug)
    _record_book_generation_job(
        job_id,
        stage="review_exported",
        message=f"Prepared {scene_result['prepared_count']} editable review scenes.",
        progress=99,
        status="running",
        scenes_prepared=scene_result["prepared_count"],
        scenes_images_linked=scene_result["images_linked"],
        scenes_text_layers=scene_result["text_layers_updated"],
    )
    _record_book_generation_job(
        job_id,
        stage="complete",
        message=f"{final_message} {_artifact_audit_message(artifact_audit)}",
        progress=100,
        status="done",
        images_created=len(result.images),
        review_files=len(result.review_files),
        draft_pdf=str(result.pdf_path or ""),
        production_pdf=str(result.production_pdf_path or ""),
        idml=str(result.idml_path or ""),
        artifact_audit=artifact_audit,
        workflow_url=f"/workflow?book_slug={book_slug}",
        review_url=f"/story-maker?book_slug={book_slug}&page=1",
        assembly_url=f"/book-assembly?book_slug={book_slug}",
    )
