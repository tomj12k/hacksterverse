"""FastAPI web app for Hackster Studio."""

from __future__ import annotations

from urllib.parse import urlparse
import json
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from sqlmodel import Session, func, select

from .api import router as api_router
from .config import PROJECT_ROOT, asset_serve_roots
from .job_store import load_job, recover_orphaned_jobs
from .jobs import (
    BookGenerationJob,  # noqa: F401  re-exported for tests/routes that construct jobs
    artifact_audit_message,
    assert_full_book_generation_complete,
    assert_page_image_generation_complete,
    book_generation_executor,
    book_generation_job_payload,
    book_generation_jobs,
    book_generation_jobs_lock,
    generate_single_character_pack,
    reference_pack_image_count,
    start_book_generation_job,
)
from .pathsafe import is_within_any, resolve_within
from .database import get_session, init_db
from .models import Book, Character, Environment, Gadget, Page, PrintReport, Project, Prompt
from .services.books import (
    create_book,
    delete_book,
    generate_book_from_brief,
    generate_book_from_dgx_brief,
    generate_book_from_openai_brief,
    get_book_by_slug,
    get_pages_for_book,
    list_books,
    plan_book,
    read_planning_brief,
    update_book_metadata,
    update_book_page,
    write_page_yaml,
)
from .services.characters import get_character, list_characters
from .services.character_training import (
    character_training_bench,
    delete_character_image,
    delete_character_images,
    delete_reference_pack,
    list_asset_character_cards,
    prepare_lora_dataset,
    process_training_selection,
    save_lora_settings,
    save_character_design_lock,
    start_lora_training,
    training_status_payload,
)
from .services.ai_planner import AIPlannerUnavailable, openai_settings, regenerate_page_with_dgx, write_openai_settings
from .services.environments import list_environments
from .services.exports import export_page_spec_yaml, export_page_specs_yaml
from .services.gadgets import list_gadgets
from .services.pages import get_page, update_page_text
from .services.print_validator import validate_image_for_print
from .services.prompts import (
    generate_character_prompt,
    generate_environment_prompt,
    generate_gadget_prompt,
    generate_page_prompt,
    generate_prompts_for_book,
    list_prompts,
)
from .page_ops import (
    nearby_page_context,
    page_for_book,
    refresh_book_page_prompt_package,
    refresh_scene_image_from_page,
    refresh_scene_text_from_page,
)
from .services.artifacts import book_artifact_counts, count_page_files, first_missing_image_page
from .services.consistency import book_consistency_report
from .services.story_maker import book_page_count, book_readiness, load_scene
from .automation import dgx_services
from .automation.pipeline import status_book


init_db()

# Job data model + infrastructure live in .jobs; underscore aliases preserve
# the existing in-module references and test monkeypatch targets.
_book_generation_executor = book_generation_executor
_book_generation_jobs = book_generation_jobs
_book_generation_jobs_lock = book_generation_jobs_lock
_book_generation_job_payload = book_generation_job_payload


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Crash recovery: any job left queued/running in the DB belongs to a prior
    # process whose in-memory state is gone — mark those as failed.
    recover_orphaned_jobs()
    yield
    # Graceful shutdown: stop accepting new jobs; don't block ASGI teardown on
    # in-flight ones (the executor's atexit join still lets them finish).
    _book_generation_executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="Hackster Studio", lifespan=_lifespan)
app.include_router(api_router, prefix="/api")
templates = Jinja2Templates(directory=PROJECT_ROOT / "hackster_studio" / "templates")
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "hackster_studio" / "static"), name="static")

_CSRF_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


@app.middleware("http")
async def csrf_origin_guard(request: Request, call_next):
    """Reject cross-site state-changing requests via an Origin check.

    Browsers always send an ``Origin`` header on POST/PUT/DELETE/PATCH, so a
    mismatched origin marks a cross-site (CSRF) attempt. Requests without an
    Origin (server-to-server, curl, the test client) are not browser CSRF and
    are allowed — this keeps the API usable while blocking forged form posts.
    """
    if request.method not in _CSRF_SAFE_METHODS:
        origin = request.headers.get("origin")
        if origin:
            origin_host = urlparse(origin).netloc
            request_host = request.headers.get("host", "")
            if origin_host != request_host:
                return JSONResponse(
                    {"detail": "Cross-site request blocked (origin mismatch)."},
                    status_code=403,
                )
    return await call_next(request)


DEFAULT_BOOK_SLUG = "book01_password_dragon"
CURRENT_BOOK_COOKIE = "hackster_current_book"


def count(session: Session, model: type) -> int:
    return int(session.exec(select(func.count()).select_from(model)).one())


def current_book_slug(request: Request, session: Session, requested_slug: str | None = None) -> str:
    if requested_slug:
        return requested_slug
    cookie_slug = request.cookies.get(CURRENT_BOOK_COOKIE)
    if cookie_slug and get_book_by_slug(session, cookie_slug):
        return cookie_slug
    books = list_books(session)
    return books[0].slug if books else DEFAULT_BOOK_SLUG


def book_nav_context(session: Session, book_slug: str) -> dict[str, object]:
    return {
        "book_nav": {
            "books": list_books(session),
            "current_slug": book_slug,
            "current": get_book_by_slug(session, book_slug),
        }
    }


def form_int(value: object, default: int) -> int:
    try:
        return int(str(value or default))
    except (TypeError, ValueError):
        return default


def workflow_context(book_slug: str = DEFAULT_BOOK_SLUG) -> dict[str, object]:
    status = status_book(book_slug)
    root = Path(status["root"])
    production_pdf = root / "exports" / "lulu" / f"{book_slug}_interior_lulu_print.pdf"
    idml = root / "exports" / "affinity" / f"{book_slug}_affinity_starter.idml"
    expected_pages = max(1, book_page_count(book_slug))

    pages = int(status["pages"])
    prompts = int(status["prompts"])
    images = int(status["images"])
    reviews = int(status["reviews"])
    approved = int(status["approved_pages"])

    generation_complete = pages >= expected_pages and prompts >= expected_pages and images >= expected_pages
    steps = [
        {
            "number": 1,
            "title": "Generate Book",
            "status": "complete" if generation_complete else "next",
            "progress": f"{pages}/{expected_pages} pages · {prompts}/{expected_pages} prompts · {images}/{expected_pages} images",
            "href": f"/book-generation?book_slug={book_slug}",
            "action": "Open Book Generation",
        },
        {
            "number": 2,
            "title": "Review And Touch Up",
            "status": "complete" if approved >= expected_pages else ("next" if images >= expected_pages else "locked"),
            "progress": f"{approved}/{expected_pages} approved",
            "href": f"/story-maker?book_slug={book_slug}&page=1",
            "action": "Open Story Maker",
        },
        {
            "number": 3,
            "title": "QA Gate",
            "status": "complete" if reviews >= expected_pages and approved >= 1 else ("next" if images >= 1 else "locked"),
            "progress": f"{reviews}/{expected_pages} review files",
            "href": "/print-validator",
            "action": "Open QA",
        },
        {
            "number": 4,
            "title": "Export For Print",
            "status": "complete" if production_pdf.exists() and idml.exists() else ("next" if approved >= expected_pages else "locked"),
            "progress": "Lulu PDF + IDML" if production_pdf.exists() and idml.exists() else "exports pending",
            "href": f"/books/{book_slug}",
            "action": "Open Exports",
        },
    ]

    return {
        "book_slug": book_slug,
        "expected_pages": expected_pages,
        "status": status,
        "steps": steps,
        "production_pdf_exists": production_pdf.exists(),
        "idml_exists": idml.exists(),
        "production_pdf": production_pdf,
        "idml": idml,
    }


def generate_planned_book(
    session: Session,
    book_slug: str,
    *,
    planner_engine: str,
    idea: str,
    characters: str,
    objects: str,
    character_count: int,
    object_count: int,
    reference_notes: str,
) -> None:
    if planner_engine == "openai":
        generate_book_from_openai_brief(
            session,
            book_slug,
            idea=idea,
            characters=characters,
            objects=objects,
            character_count=character_count,
            object_count=object_count,
            reference_notes=reference_notes,
        )
    elif planner_engine == "dgx":
        generate_book_from_dgx_brief(
            session,
            book_slug,
            idea=idea,
            characters=characters,
            objects=objects,
            character_count=character_count,
            object_count=object_count,
            reference_notes=reference_notes,
        )
    else:
        generate_book_from_brief(
            session,
            book_slug,
            idea=idea,
            characters=characters,
            objects=objects,
            character_count=character_count,
            object_count=object_count,
            reference_notes=reference_notes,
        )
    generate_prompts_for_book(session, book_slug)
    export_page_specs_yaml(session, book_slug)


def _generation_payload_from_form(form: object) -> dict[str, Any]:
    return {
        "idea": str(form.get("idea", "")),
        "characters": str(form.get("characters", "")),
        "objects": str(form.get("objects", "")),
        "character_count": form_int(form.get("character_count"), 3),
        "object_count": form_int(form.get("object_count"), 4),
        "reference_notes": str(form.get("reference_notes", "")),
    }


# Job orchestration relocated to .jobs (imported below); routes call
# start_book_generation_job, tests patch _run_book_generation_job.


# Artifact-audit helpers moved to .jobs; aliases preserve call sites + tests.
_assert_full_book_generation_complete = assert_full_book_generation_complete
_assert_page_image_generation_complete = assert_page_image_generation_complete
_artifact_audit_message = artifact_audit_message


# Artifact-counting moved to services.artifacts; these aliases preserve the
# existing internal call sites.
_first_missing_image_page = first_missing_image_page
_book_artifact_counts = book_artifact_counts
_count_page_files = count_page_files


# Page operations moved to page_ops; aliases preserve existing call sites.
_page_for_book = page_for_book
_nearby_page_context = nearby_page_context
_refresh_scene_text_from_page = refresh_scene_text_from_page
_refresh_scene_image_from_page = refresh_scene_image_from_page
_refresh_book_page_prompt_package = refresh_book_page_prompt_package


def _wants_generation_job(request: Request, planner_engine: str) -> bool:
    return (
        planner_engine == "dgx"
        and request.headers.get("x-requested-with", "").lower() == "fetch"
    )


def book_generation_phases(status: dict[str, object], expected_pages: int) -> list[dict[str, str]]:
    pages = int(status["pages"])
    prompts = int(status["prompts"])
    images = int(status["images"])
    approved = int(status["approved_pages"])
    reviews = int(status["reviews"])
    return [
        {
            "title": "DGX Layout And Story",
            "status": "complete" if pages >= expected_pages else "next",
            "detail": f"{pages}/{expected_pages} planned pages",
        },
        {
            "title": "Prompt Package",
            "status": "complete" if prompts >= expected_pages else ("next" if pages >= expected_pages else "locked"),
            "detail": f"{prompts}/{expected_pages} image prompts",
        },
        {
            "title": "Illustrations And Character Layers",
            "status": "complete" if images >= expected_pages else ("next" if prompts >= expected_pages else "locked"),
            "detail": f"{images}/{expected_pages} illustrations",
        },
        {
            "title": "Editable Review",
            "status": "complete" if approved >= expected_pages else ("next" if images >= 1 else "locked"),
            "detail": f"{approved}/{expected_pages} approved pages",
        },
        {
            "title": "QA And Export",
            "status": "complete" if reviews >= expected_pages and approved >= expected_pages else ("next" if approved >= 1 else "locked"),
            "detail": f"{reviews}/{expected_pages} review files",
        },
    ]


@app.get("/api/dgx/planner-log")
def dgx_planner_log(lines: int = 80) -> JSONResponse:
    try:
        log_text = dgx_services.read_dgx_planner_log(lines=lines)
    except Exception as exc:
        return JSONResponse(
            {
                "available": False,
                "source": "DGX vLLM planner log",
                "log": str(exc),
            },
            status_code=200,
        )
    return JSONResponse(
        {
            "available": True,
            "source": "DGX vLLM planner log",
            "log": log_text,
        }
    )


@app.get("/api/book-generation/jobs/{job_id}")
def book_generation_job_status(job_id: str) -> JSONResponse:
    with _book_generation_jobs_lock:
        job = _book_generation_jobs.get(job_id)
        payload = _book_generation_job_payload(job) if job is not None else None
    if payload is None:
        # Not in memory (e.g. after a restart) — fall back to the durable record.
        payload = load_job(job_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Book generation job not found")
    return JSONResponse(payload)


@app.get("/api/book-generation/jobs")
def book_generation_jobs() -> JSONResponse:
    with _book_generation_jobs_lock:
        jobs = [_book_generation_job_payload(job) for job in _book_generation_jobs.values()]
    jobs.sort(key=lambda item: str(item["job_id"]), reverse=True)
    return JSONResponse({"jobs": jobs[-20:]})


@app.get("/api/books/{book_slug}/consistency")
def book_consistency(book_slug: str, session: Session = Depends(get_session)) -> JSONResponse:
    try:
        return JSONResponse(book_consistency_report(session, book_slug))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    active_slug = current_book_slug(request, session)
    counts = {
        "projects": count(session, Project),
        "characters": count(session, Character),
        "environments": count(session, Environment),
        "gadgets": count(session, Gadget),
        "books": count(session, Book),
        "pages": count(session, Page),
        "prompts": count(session, Prompt),
        "print_reports": count(session, PrintReport),
    }
    latest_books = list_books(session)
    context = {
        "counts": counts,
        "books": latest_books,
        "workflow": workflow_context(active_slug),
        **book_nav_context(session, active_slug),
    }
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        context,
    )


@app.get("/workflow", response_class=HTMLResponse)
def workflow(
    request: Request,
    book_slug: str | None = None,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    active_slug = current_book_slug(request, session, book_slug)
    return templates.TemplateResponse(
        request,
        "workflow.html",
        {**workflow_context(active_slug), **book_nav_context(session, active_slug)},
    )


@app.get("/book-generation", response_class=HTMLResponse)
def book_generation(
    request: Request,
    book_slug: str | None = None,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    active_slug = current_book_slug(request, session, book_slug)
    book = get_book_by_slug(session, active_slug)
    workflow = workflow_context(active_slug)
    return templates.TemplateResponse(
        request,
        "book_generation.html",
        {
            "book": book,
            "book_slug": active_slug,
            "planner_brief": read_planning_brief(active_slug) if book else {},
            "ai_settings": openai_settings(),
            "workflow": workflow,
            "generation_phases": book_generation_phases(workflow["status"], int(workflow["expected_pages"])),
            **book_nav_context(session, active_slug),
        },
    )


@app.get("/book-assembly", response_class=HTMLResponse)
def book_assembly(
    request: Request,
    book_slug: str | None = None,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    active_slug = current_book_slug(request, session, book_slug)
    readiness = book_readiness(active_slug)
    return templates.TemplateResponse(
        request,
        "book_assembly.html",
        {"readiness": readiness, **book_nav_context(session, active_slug)},
    )


@app.get("/characters", response_class=HTMLResponse)
def characters(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "characters.html",
        {
            "title": "Character Library",
            "kind": "characters",
            "items": list_characters(session),
            "asset_characters": list_asset_character_cards(),
        },
    )


@app.get("/characters/{character_id}", response_class=HTMLResponse)
def character_detail(
    request: Request,
    character_id: int,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    character = get_character(session, character_id)
    bench = character_training_bench(character.name, character.slug) if character else None
    return templates.TemplateResponse(
        request,
        "character_detail.html",
        {
            "character": character,
            "training_bench": bench,
            "character_action_base": f"/characters/{character_id}",
        },
    )


@app.get("/characters/by-slug/{character_slug}", response_class=HTMLResponse)
def character_detail_by_slug(request: Request, character_slug: str, session: Session = Depends(get_session)) -> HTMLResponse:
    from types import SimpleNamespace

    character = session.exec(select(Character).where(Character.slug == character_slug)).first()
    if character is None:
        name = character_slug.replace("_", " ").replace("-", " ").title()
        character = SimpleNamespace(
            id=None,
            name=name,
            slug=character_slug,
            role="Layered story character",
            description="Character generated or planned through the layered production pipeline.",
            appearance="Use the reference pack and selected examples as the source of truth.",
            personality="",
            colors_json="{}",
            style_notes="",
        )
    bench = character_training_bench(character.name, character.slug)
    return templates.TemplateResponse(
        request,
        "character_detail.html",
        {
            "character": character,
            "training_bench": bench,
            "character_action_base": f"/characters/by-slug/{character_slug}",
        },
    )


@app.post("/characters/{character_id}/generate-prompt")
def generate_character_prompt_route(character_id: int, session: Session = Depends(get_session)) -> RedirectResponse:
    character = get_character(session, character_id)
    if character:
        generate_character_prompt(session, character)
    return RedirectResponse(f"/characters/{character_id}", status_code=303)


@app.post("/characters/{character_id}/generate-reference-pack")
async def generate_character_reference_pack_route(
    request: Request,
    character_id: int,
    session: Session = Depends(get_session),
) -> Response:
    character = get_character(session, character_id)
    if character:
        form = await request.form()
        image_count = _reference_pack_image_count(form.get("image_count"))
        redirect_url = f"/characters/{character_id}"
        if _request_wants_json(request):
            job = start_book_generation_job(
                f"character_{character.slug}",
                {
                    "run_mode": "single_character_reference",
                    "character_name": character.name,
                    "character_slug": character.slug,
                    "force": bool(form.get("force")),
                    "image_count": image_count,
                    "redirect_url": redirect_url,
                },
            )
            return JSONResponse(_book_generation_job_payload(job))
        _generate_single_character_pack(character.name, character.slug, force=bool(form.get("force")), image_count=image_count)
    return RedirectResponse(f"/characters/{character_id}", status_code=303)


@app.post("/characters/by-slug/{character_slug}/generate-reference-pack")
async def generate_character_reference_pack_by_slug_route(request: Request, character_slug: str) -> Response:
    form = await request.form()
    name = str(form.get("character_name") or character_slug.replace("_", " ").title())
    image_count = _reference_pack_image_count(form.get("image_count"))
    redirect_url = f"/characters/by-slug/{character_slug}"
    if _request_wants_json(request):
        job = start_book_generation_job(
            f"character_{character_slug}",
            {
                "run_mode": "single_character_reference",
                "character_name": name,
                "character_slug": character_slug,
                "force": bool(form.get("force")),
                "image_count": image_count,
                "redirect_url": redirect_url,
            },
        )
        return JSONResponse(_book_generation_job_payload(job))
    _generate_single_character_pack(name, character_slug, force=bool(form.get("force")), image_count=image_count)
    return RedirectResponse(f"/characters/by-slug/{character_slug}", status_code=303)


@app.post("/characters/{character_id}/training-selection")
async def save_character_training_selection_route(
    request: Request,
    character_id: int,
    session: Session = Depends(get_session),
) -> RedirectResponse:
    manifest = None
    character = get_character(session, character_id)
    if character:
        form = await request.form()
        manifest = process_training_selection(character.slug, [str(item) for item in form.getlist("selected_images")], name=character.name)
    if _request_wants_json(request):
        return JSONResponse(training_status_payload(manifest or {}))
    return RedirectResponse(f"/characters/{character_id}", status_code=303)


@app.post("/characters/by-slug/{character_slug}/training-selection")
async def save_character_training_selection_by_slug_route(request: Request, character_slug: str) -> Response:
    form = await request.form()
    name = str(form.get("character_name") or character_slug.replace("_", " ").title())
    manifest = process_training_selection(character_slug, [str(item) for item in form.getlist("selected_images")], name=name)
    if _request_wants_json(request):
        return JSONResponse(training_status_payload(manifest))
    return RedirectResponse(f"/characters/by-slug/{character_slug}", status_code=303)


@app.post("/characters/{character_id}/delete-image")
async def delete_character_image_route(
    request: Request,
    character_id: int,
    session: Session = Depends(get_session),
) -> RedirectResponse:
    character = get_character(session, character_id)
    if character:
        form = await request.form()
        delete_character_image(character.slug, str(form.get("image_path") or ""), name=character.name)
    return RedirectResponse(f"/characters/{character_id}", status_code=303)


@app.post("/characters/by-slug/{character_slug}/delete-image")
async def delete_character_image_by_slug_route(request: Request, character_slug: str) -> RedirectResponse:
    form = await request.form()
    name = str(form.get("character_name") or character_slug.replace("_", " ").title())
    delete_character_image(character_slug, str(form.get("image_path") or ""), name=name)
    return RedirectResponse(f"/characters/by-slug/{character_slug}", status_code=303)


@app.post("/characters/{character_id}/delete-selected-images")
async def delete_selected_character_images_route(
    request: Request,
    character_id: int,
    session: Session = Depends(get_session),
) -> RedirectResponse:
    character = get_character(session, character_id)
    if character:
        form = await request.form()
        delete_character_images(character.slug, [str(item) for item in form.getlist("selected_images")], name=character.name)
    return RedirectResponse(f"/characters/{character_id}", status_code=303)


@app.post("/characters/by-slug/{character_slug}/delete-selected-images")
async def delete_selected_character_images_by_slug_route(request: Request, character_slug: str) -> RedirectResponse:
    form = await request.form()
    name = str(form.get("character_name") or character_slug.replace("_", " ").title())
    delete_character_images(character_slug, [str(item) for item in form.getlist("selected_images")], name=name)
    return RedirectResponse(f"/characters/by-slug/{character_slug}", status_code=303)


@app.post("/characters/{character_id}/delete-reference-pack")
async def delete_character_reference_pack_route(
    request: Request,
    character_id: int,
    session: Session = Depends(get_session),
) -> RedirectResponse:
    character = get_character(session, character_id)
    if character:
        delete_reference_pack(character.slug, name=character.name)
    return RedirectResponse(f"/characters/{character_id}", status_code=303)


@app.post("/characters/by-slug/{character_slug}/delete-reference-pack")
async def delete_character_reference_pack_by_slug_route(request: Request, character_slug: str) -> RedirectResponse:
    form = await request.form()
    name = str(form.get("character_name") or character_slug.replace("_", " ").title())
    delete_reference_pack(character_slug, name=name)
    return RedirectResponse(f"/characters/by-slug/{character_slug}", status_code=303)


@app.post("/characters/{character_id}/design-lock")
async def save_character_design_lock_route(
    request: Request,
    character_id: int,
    session: Session = Depends(get_session),
) -> RedirectResponse:
    character = get_character(session, character_id)
    if character:
        form = await request.form()
        save_character_design_lock(character.slug, str(form.get("design_lock") or ""), name=character.name)
    return RedirectResponse(f"/characters/{character_id}", status_code=303)


@app.post("/characters/by-slug/{character_slug}/design-lock")
async def save_character_design_lock_by_slug_route(request: Request, character_slug: str) -> RedirectResponse:
    form = await request.form()
    name = str(form.get("character_name") or character_slug.replace("_", " ").title())
    save_character_design_lock(character_slug, str(form.get("design_lock") or ""), name=name)
    return RedirectResponse(f"/characters/by-slug/{character_slug}", status_code=303)


@app.post("/characters/{character_id}/prepare-lora")
async def prepare_character_lora_route(
    request: Request,
    character_id: int,
    session: Session = Depends(get_session),
) -> RedirectResponse:
    character = get_character(session, character_id)
    if character:
        form = await request.form()
        if form.getlist("selected_images"):
            process_training_selection(character.slug, [str(item) for item in form.getlist("selected_images")], name=character.name)
        prepare_lora_dataset(character.slug, name=character.name)
    return RedirectResponse(f"/characters/{character_id}", status_code=303)


@app.post("/characters/by-slug/{character_slug}/prepare-lora")
async def prepare_character_lora_by_slug_route(request: Request, character_slug: str) -> RedirectResponse:
    form = await request.form()
    name = str(form.get("character_name") or character_slug.replace("_", " ").title())
    if form.getlist("selected_images"):
        process_training_selection(character_slug, [str(item) for item in form.getlist("selected_images")], name=name)
    prepare_lora_dataset(character_slug, name=name)
    return RedirectResponse(f"/characters/by-slug/{character_slug}", status_code=303)


@app.post("/characters/{character_id}/train-lora")
async def train_character_lora_route(
    request: Request,
    character_id: int,
    session: Session = Depends(get_session),
) -> RedirectResponse:
    character = get_character(session, character_id)
    if character:
        form = await request.form()
        if form.getlist("selected_images"):
            process_training_selection(character.slug, [str(item) for item in form.getlist("selected_images")], name=character.name)
        start_lora_training(character.slug, name=character.name)
    return RedirectResponse(f"/characters/{character_id}", status_code=303)


@app.post("/characters/by-slug/{character_slug}/train-lora")
async def train_character_lora_by_slug_route(request: Request, character_slug: str) -> RedirectResponse:
    form = await request.form()
    name = str(form.get("character_name") or character_slug.replace("_", " ").title())
    if form.getlist("selected_images"):
        process_training_selection(character_slug, [str(item) for item in form.getlist("selected_images")], name=name)
    start_lora_training(character_slug, name=name)
    return RedirectResponse(f"/characters/by-slug/{character_slug}", status_code=303)


@app.post("/characters/{character_id}/lora-settings")
async def save_character_lora_settings_route(
    request: Request,
    character_id: int,
    session: Session = Depends(get_session),
) -> RedirectResponse:
    character = get_character(session, character_id)
    if character:
        form = await request.form()
        save_lora_settings(
            character.slug,
            name=character.name,
            lora_name=str(form.get("lora_name") or ""),
            lora_path=str(form.get("lora_path") or ""),
            trigger=str(form.get("trigger") or ""),
        )
    return RedirectResponse(f"/characters/{character_id}", status_code=303)


@app.post("/characters/by-slug/{character_slug}/lora-settings")
async def save_character_lora_settings_by_slug_route(request: Request, character_slug: str) -> RedirectResponse:
    form = await request.form()
    name = str(form.get("character_name") or character_slug.replace("_", " ").title())
    save_lora_settings(
        character_slug,
        name=name,
        lora_name=str(form.get("lora_name") or ""),
        lora_path=str(form.get("lora_path") or ""),
        trigger=str(form.get("trigger") or ""),
    )
    return RedirectResponse(f"/characters/by-slug/{character_slug}", status_code=303)


# Character-pack helpers moved to .jobs; aliases preserve route call sites.
_generate_single_character_pack = generate_single_character_pack
_reference_pack_image_count = reference_pack_image_count


def _request_wants_json(request: Request) -> bool:
    return request.headers.get("x-requested-with", "").lower() == "fetch"


@app.get("/environments", response_class=HTMLResponse)
def environments(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "characters.html",
        {"title": "World / Environment Library", "kind": "environments", "items": list_environments(session)},
    )


@app.post("/environments/{environment_id}/generate-prompt")
def generate_environment_prompt_route(
    environment_id: int,
    session: Session = Depends(get_session),
) -> RedirectResponse:
    environment_model = session.get(Environment, environment_id)
    if environment_model:
        generate_environment_prompt(session, environment_model)
    return RedirectResponse("/environments", status_code=303)


@app.get("/gadgets", response_class=HTMLResponse)
def gadgets(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "characters.html",
        {"title": "Gadget Library", "kind": "gadgets", "items": list_gadgets(session)},
    )


@app.post("/gadgets/{gadget_id}/generate-prompt")
def generate_gadget_prompt_route(gadget_id: int, session: Session = Depends(get_session)) -> RedirectResponse:
    gadget = session.get(Gadget, gadget_id)
    if gadget:
        generate_gadget_prompt(session, gadget)
    return RedirectResponse("/gadgets", status_code=303)


@app.get("/books", response_class=HTMLResponse)
def books(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    active_slug = current_book_slug(request, session)
    return templates.TemplateResponse(
        request,
        "books.html",
        {
            "books": list_books(session),
            "ai_settings": openai_settings(),
            **book_nav_context(session, active_slug),
        },
    )


@app.post("/books")
async def create_book_route(request: Request, session: Session = Depends(get_session)) -> Response:
    form = await request.form()
    planner_engine = str(form.get("planner_engine", ""))
    if planner_engine == "openai" and not openai_settings()["api_key_configured"]:
        raise HTTPException(status_code=400, detail="OpenAI is not configured. Open AI Setup and add OPENAI_API_KEY.")
    if planner_engine == "dgx" and not openai_settings()["dgx_configured"]:
        raise HTTPException(status_code=400, detail="DGX planner is not configured. Open AI Setup and add DGX_LLM_BASE_URL.")
    book = create_book(
        session,
        title=str(form.get("title", "")),
        slug=str(form.get("slug", "")),
        series=str(form.get("series", "Hackster Niko")),
        target_age=str(form.get("target_age", "5-8")),
        lesson=str(form.get("lesson", "")),
        page_count=form_int(form.get("page_count"), 32),
        trim_size=str(form.get("trim_size", "8.5x8.5")),
    )
    idea = str(form.get("idea", "")).strip()
    if form.get("generate_book") or planner_engine in {"local", "openai", "dgx"}:
        planner_engine = planner_engine or "local"
        if _wants_generation_job(request, planner_engine):
            job = start_book_generation_job(book.slug, _generation_payload_from_form(form))
            response = JSONResponse(_book_generation_job_payload(job))
            response.set_cookie(CURRENT_BOOK_COOKIE, book.slug, max_age=60 * 60 * 24 * 365, samesite="lax")
            return response
        try:
            await run_in_threadpool(
                partial(
                    generate_planned_book,
                    session,
                    book.slug,
                    planner_engine=planner_engine,
                    idea=idea,
                    characters=str(form.get("characters", "")),
                    objects=str(form.get("objects", "")),
                    character_count=form_int(form.get("character_count"), 3),
                    object_count=form_int(form.get("object_count"), 4),
                    reference_notes=str(form.get("reference_notes", "")),
                )
            )
        except AIPlannerUnavailable as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    response = RedirectResponse(f"/books/{book.slug}", status_code=303)
    response.set_cookie(CURRENT_BOOK_COOKIE, book.slug, max_age=60 * 60 * 24 * 365, samesite="lax")
    return response


@app.post("/books/{book_slug}/set-current")
def set_current_book_route(book_slug: str, session: Session = Depends(get_session)) -> RedirectResponse:
    if not get_book_by_slug(session, book_slug):
        raise HTTPException(status_code=404, detail="Book not found")
    response = RedirectResponse("/workflow", status_code=303)
    response.set_cookie(CURRENT_BOOK_COOKIE, book_slug, max_age=60 * 60 * 24 * 365, samesite="lax")
    return response


@app.post("/books/{book_slug}/delete")
def delete_book_route(
    request: Request,
    book_slug: str,
    session: Session = Depends(get_session),
) -> RedirectResponse:
    try:
        delete_book(session, book_slug)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    with _book_generation_jobs_lock:
        for job_id, job in list(_book_generation_jobs.items()):
            if job.book_slug == book_slug:
                _book_generation_jobs.pop(job_id, None)

    remaining_books = list_books(session)
    response = RedirectResponse("/books", status_code=303)
    if request.cookies.get(CURRENT_BOOK_COOKIE) == book_slug:
        if remaining_books:
            response.set_cookie(
                CURRENT_BOOK_COOKIE,
                remaining_books[0].slug,
                max_age=60 * 60 * 24 * 365,
                samesite="lax",
            )
        else:
            response.delete_cookie(CURRENT_BOOK_COOKIE)
    return response


@app.get("/books/{book_slug}", response_class=HTMLResponse)
def book_detail(
    request: Request,
    book_slug: str,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    book = get_book_by_slug(session, book_slug)
    pages = get_pages_for_book(session, book.id) if book and book.id else []
    return templates.TemplateResponse(
        request,
        "book_detail.html",
        {
            "book": book,
            "pages": pages,
            "planner_brief": read_planning_brief(book_slug) if book else {},
            "ai_settings": openai_settings(),
            **book_nav_context(session, book_slug),
        },
    )


@app.post("/books/{book_slug}/edit")
async def edit_book_route(
    request: Request,
    book_slug: str,
    session: Session = Depends(get_session),
) -> RedirectResponse:
    form = await request.form()
    update_book_metadata(
        session,
        book_slug,
        title=str(form.get("title", "")),
        series=str(form.get("series", "")),
        target_age=str(form.get("target_age", "")),
        lesson=str(form.get("lesson", "")),
        status=str(form.get("status", "")),
    )
    return RedirectResponse(f"/books/{book_slug}", status_code=303)


@app.post("/books/{book_slug}/generate-book")
async def generate_book_route(
    request: Request,
    book_slug: str,
    session: Session = Depends(get_session),
) -> Response:
    form = await request.form()
    planner_engine = str(form.get("planner_engine", "local"))
    if planner_engine == "openai" and not openai_settings()["api_key_configured"]:
        raise HTTPException(status_code=400, detail="OpenAI is not configured. Open AI Setup and add OPENAI_API_KEY.")
    if planner_engine == "dgx" and not openai_settings()["dgx_configured"]:
        raise HTTPException(status_code=400, detail="DGX planner is not configured. Open AI Setup and add DGX_LLM_BASE_URL.")
    if _wants_generation_job(request, planner_engine):
        job = start_book_generation_job(book_slug, _generation_payload_from_form(form))
        response = JSONResponse(_book_generation_job_payload(job))
        response.set_cookie(CURRENT_BOOK_COOKIE, book_slug, max_age=60 * 60 * 24 * 365, samesite="lax")
        return response
    try:
        await run_in_threadpool(
            partial(
                generate_planned_book,
                session,
                book_slug,
                planner_engine=planner_engine,
                idea=str(form.get("idea", "")),
                characters=str(form.get("characters", "")),
                objects=str(form.get("objects", "")),
                character_count=form_int(form.get("character_count"), 3),
                object_count=form_int(form.get("object_count"), 4),
                reference_notes=str(form.get("reference_notes", "")),
            )
        )
    except AIPlannerUnavailable as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response = RedirectResponse(f"/books/{book_slug}", status_code=303)
    response.set_cookie(CURRENT_BOOK_COOKIE, book_slug, max_age=60 * 60 * 24 * 365, samesite="lax")
    return response


@app.post("/books/{book_slug}/resume-generation")
def resume_generation_route(book_slug: str) -> JSONResponse:
    job = start_book_generation_job(book_slug, {"run_mode": "resume"})
    return JSONResponse(_book_generation_job_payload(job))


@app.post("/books/{book_slug}/generate-character-references")
async def generate_character_references_route(request: Request, book_slug: str) -> JSONResponse:
    form = await request.form()
    job = start_book_generation_job(book_slug, {"run_mode": "characters", "force": bool(form.get("force"))})
    return JSONResponse(_book_generation_job_payload(job))


@app.post("/api/books/{book_slug}/pages/{page_number}/regenerate-story")
def regenerate_page_story_route(
    book_slug: str,
    page_number: int,
    session: Session = Depends(get_session),
) -> JSONResponse:
    from .automation.dgx_services import prepare_dgx_planner

    book = get_book_by_slug(session, book_slug)
    if book is None or book.id is None:
        raise HTTPException(status_code=404, detail="Book not found")
    page = _page_for_book(session, book, page_number)
    brief = read_planning_brief(book_slug)
    prepare_dgx_planner()
    try:
        replacement = regenerate_page_with_dgx(
            title=book.title,
            idea=str(brief.get("idea") or ""),
            lesson=book.lesson,
            page_count=book.page_count,
            page_number=page_number,
            target_age=book.target_age,
            characters=[str(item) for item in (brief.get("focus_characters") or [])],
            objects=[str(item) for item in (brief.get("focus_items") or [])],
            reference_notes=str(brief.get("reference_notes") or ""),
            page_context=_nearby_page_context(session, book, page_number),
        )
    except AIPlannerUnavailable as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    page.page_type = str(replacement["page_type"])
    page.scene_title = str(replacement["scene_title"])
    page.story_text = str(replacement["story_text"])
    page.illustration_direction = str(replacement["illustration_direction"])
    page.characters_json = json.dumps(replacement["characters"])
    page.environment = str(replacement["environment"])
    page.emotion = str(replacement["emotion"])
    page.camera = str(replacement["camera"])
    page.hidden_objects_json = json.dumps(replacement["hidden_objects"])
    page.text_safe_area = str(replacement["text_safe_area"])
    page.status = "AI replanned"
    session.add(page)
    session.commit()
    session.refresh(page)
    write_page_yaml(book, page)
    prompt = generate_page_prompt(session, page)
    spec_path = export_page_spec_yaml(session, book_slug, page_number)
    _refresh_book_page_prompt_package(book_slug, page_number)
    _refresh_scene_text_from_page(book_slug, page_number, page.story_text)
    return JSONResponse(
        {
            "status": "done",
            "page_number": page_number,
            "scene_title": page.scene_title,
            "story_text": page.story_text,
            "illustration_direction": page.illustration_direction,
            "prompt_path": prompt.output_path,
            "page_spec": spec_path.as_posix(),
        }
    )


@app.post("/api/books/{book_slug}/pages/{page_number}/regenerate-prompt")
def regenerate_page_prompt_route(
    book_slug: str,
    page_number: int,
    session: Session = Depends(get_session),
) -> JSONResponse:
    book = get_book_by_slug(session, book_slug)
    if book is None or book.id is None:
        raise HTTPException(status_code=404, detail="Book not found")
    page = _page_for_book(session, book, page_number)
    prompt = generate_page_prompt(session, page)
    spec_path = export_page_spec_yaml(session, book_slug, page_number)
    _refresh_book_page_prompt_package(book_slug, page_number)
    return JSONResponse(
        {
            "status": "done",
            "page_number": page_number,
            "prompt_path": prompt.output_path,
            "page_spec": spec_path.as_posix(),
        }
    )


@app.post("/api/books/{book_slug}/pages/{page_number}/regenerate-image")
def regenerate_page_image_route(book_slug: str, page_number: int) -> JSONResponse:
    job = start_book_generation_job(book_slug, {"run_mode": "page_image", "page_number": page_number})
    return JSONResponse(_book_generation_job_payload(job))


@app.post("/api/books/{book_slug}/pages/{page_number}/regenerate-all")
def regenerate_page_all_route(
    book_slug: str,
    page_number: int,
    session: Session = Depends(get_session),
) -> JSONResponse:
    regenerate_page_story_route(book_slug, page_number, session)
    job = start_book_generation_job(book_slug, {"run_mode": "page_image", "page_number": page_number})
    return JSONResponse(_book_generation_job_payload(job))


@app.get("/settings/ai", response_class=HTMLResponse)
def ai_settings_page(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    active_slug = current_book_slug(request, session)
    return templates.TemplateResponse(
        request,
        "ai_settings.html",
        {"settings": openai_settings(), "saved": False, **book_nav_context(session, active_slug)},
    )


@app.post("/settings/ai", response_class=HTMLResponse)
async def save_ai_settings_page(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    form = await request.form()
    active_slug = current_book_slug(request, session)
    try:
        write_openai_settings(
            api_key=str(form.get("openai_api_key", "")),
            text_model=str(form.get("openai_text_model", "")),
            image_model=str(form.get("openai_image_model", "")),
            dgx_base_url=str(form.get("dgx_base_url", "")),
            dgx_api_key=str(form.get("dgx_api_key", "")),
            dgx_text_model=str(form.get("dgx_text_model", "")),
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "ai_settings.html",
            {"settings": openai_settings(), "saved": False, "error": str(exc), **book_nav_context(session, active_slug)},
        )
    return templates.TemplateResponse(
        request,
        "ai_settings.html",
        {"settings": openai_settings(), "saved": True, **book_nav_context(session, active_slug)},
    )


@app.post("/books/{book_slug}/pages/{page_number}/edit")
async def edit_book_page_route(
    request: Request,
    book_slug: str,
    page_number: int,
    session: Session = Depends(get_session),
) -> RedirectResponse:
    form = await request.form()
    update_book_page(
        session,
        book_slug,
        page_number,
        scene_title=str(form.get("scene_title", "")),
        story_text=str(form.get("story_text", "")),
        illustration_direction=str(form.get("illustration_direction", "")),
        status=str(form.get("status", "")),
    )
    return RedirectResponse(f"/books/{book_slug}#page-{page_number:03d}", status_code=303)


@app.post("/books/{book_slug}/plan")
def plan_book_route(book_slug: str, session: Session = Depends(get_session)) -> RedirectResponse:
    plan_book(session, book_slug)
    return RedirectResponse(f"/books/{book_slug}", status_code=303)


@app.post("/books/{book_slug}/generate-prompts")
def generate_book_prompts_route(book_slug: str, session: Session = Depends(get_session)) -> RedirectResponse:
    generate_prompts_for_book(session, book_slug)
    return RedirectResponse(f"/books/{book_slug}", status_code=303)


@app.post("/books/{book_slug}/export-yaml")
def export_yaml_route(book_slug: str, session: Session = Depends(get_session)) -> RedirectResponse:
    export_page_specs_yaml(session, book_slug)
    return RedirectResponse(f"/books/{book_slug}", status_code=303)


@app.get("/pages/{page_id}", response_class=HTMLResponse)
def page_detail(request: Request, page_id: int, session: Session = Depends(get_session)) -> HTMLResponse:
    page = get_page(session, page_id)
    book = session.get(Book, page.book_id) if page else None
    return templates.TemplateResponse(request, "page_detail.html", {"page": page, "book": book})


@app.post("/pages/{page_id}/edit")
async def edit_page(request: Request, page_id: int, session: Session = Depends(get_session)) -> RedirectResponse:
    form = await request.form()
    update_page_text(
        session,
        page_id,
        str(form.get("story_text", "")),
        str(form.get("illustration_direction", "")),
    )
    return RedirectResponse(f"/pages/{page_id}", status_code=303)


@app.post("/pages/{page_id}/generate-prompt")
def generate_page_prompt_route(page_id: int, session: Session = Depends(get_session)) -> RedirectResponse:
    page = get_page(session, page_id)
    if page:
        generate_page_prompt(session, page)
    return RedirectResponse(f"/pages/{page_id}", status_code=303)


@app.get("/prompts", response_class=HTMLResponse)
def prompts(request: Request, prompt_id: int | None = None, session: Session = Depends(get_session)) -> HTMLResponse:
    prompt_list = list_prompts(session)
    selected = session.get(Prompt, prompt_id) if prompt_id else (prompt_list[0] if prompt_list else None)
    return templates.TemplateResponse(request, "prompts.html", {"prompts": prompt_list, "selected": selected})


@app.get("/print-validator", response_class=HTMLResponse)
def print_validator(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    reports = list(session.exec(select(PrintReport).order_by(PrintReport.created_at.desc())).all())
    return templates.TemplateResponse(request, "print_report.html", {"reports": reports, "latest": None})


@app.post("/print-validator", response_class=HTMLResponse)
async def print_validator_post(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    form = await request.form()
    image_path = str(form.get("image_path", "")).strip()
    latest = None
    error = ""
    try:
        candidate = Path(image_path).expanduser()
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate
        # image_path is untrusted form input; confine it to the project tree so
        # the validator cannot be used to probe/read arbitrary host files.
        safe_path = resolve_within(candidate, [PROJECT_ROOT])
        latest = validate_image_for_print(session, safe_path)
    except ValueError:
        error = "Image path must be inside the project."
    except Exception as exc:
        error = str(exc)
    reports = list(session.exec(select(PrintReport).order_by(PrintReport.created_at.desc())).all())
    return templates.TemplateResponse(
        request,
        "print_report.html",
        {"reports": reports, "latest": latest, "error": error},
    )


@app.get("/story-maker", response_class=HTMLResponse)
def story_maker(
    request: Request,
    book_slug: str | None = None,
    page: int = 4,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    active_slug = current_book_slug(request, session, book_slug)
    try:
        scene = load_scene(active_slug, page)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return templates.TemplateResponse(
        request,
        "story_maker.html",
        {"scene": scene, "page_count": book_page_count(active_slug), **book_nav_context(session, active_slug)},
    )


@app.get("/generate", response_class=HTMLResponse)
def generate_page(
    request: Request,
    book_slug: str | None = None,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    active_slug = current_book_slug(request, session, book_slug)
    return templates.TemplateResponse(
        request,
        "generate.html",
        {"book_slug": active_slug, **book_nav_context(session, active_slug)},
    )


@app.get("/project-assets/{asset_path:path}")
def project_asset(asset_path: str) -> FileResponse:
    target = (PROJECT_ROOT / asset_path).resolve()
    if not is_within_any(target, asset_serve_roots(PROJECT_ROOT)):
        raise HTTPException(status_code=403, detail="Asset path is outside the served asset roots.")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"Asset not found: {asset_path}")
    return FileResponse(target, headers={"Cache-Control": "no-cache"})
