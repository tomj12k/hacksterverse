"""Characterization tests for the book-generation job runners.

These pin the observable behavior of the orchestration functions (job status,
stage, and result transitions) with the heavy ComfyUI/DGX/build calls mocked.
They give the ``_run_*`` functions coverage so the code can be moved/refactored
safely. The runners live in ``hackster_studio.jobs``, so dependencies are
patched there.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import hackster_studio.jobs as jobs_mod
from hackster_studio.jobs import BookGenerationJob


@pytest.fixture(autouse=True)
def _no_db_persist(monkeypatch):
    # Keep job persistence from touching the real DB during these unit tests.
    monkeypatch.setattr(jobs_mod, "persist_job", lambda snapshot: None)
    yield


def _seed_job(slug: str = "demo") -> str:
    job = BookGenerationJob(job_id="test-job", book_slug=slug, redirect_url="/x")
    jobs_mod.book_generation_jobs["test-job"] = job
    return "test-job"


def _build_result(errors=None):
    return SimpleNamespace(
        errors=errors or [],
        images=["i1", "i2"],
        review_files=["r1"],
        pdf_path=None,
        production_pdf_path=None,
        idml_path=None,
    )


def teardown_function() -> None:
    jobs_mod.book_generation_jobs.clear()


def test_run_full_generation_reaches_done(monkeypatch) -> None:
    job_id = _seed_job()
    monkeypatch.setattr(jobs_mod, "generate_book_from_dgx_brief", lambda *a, **k: [1, 2])
    monkeypatch.setattr(jobs_mod, "generate_prompts_for_book", lambda *a, **k: ["p1", "p2"])
    monkeypatch.setattr(jobs_mod, "export_page_specs_yaml", lambda *a, **k: ["s1", "s2"])
    monkeypatch.setattr(jobs_mod, "build_book", lambda *a, **k: _build_result())
    monkeypatch.setattr(
        jobs_mod,
        "prepare_book_review_scenes",
        lambda *a, **k: {"prepared_count": 2, "images_linked": 2, "text_layers_updated": 2},
    )
    monkeypatch.setattr(jobs_mod, "_assert_full_book_generation_complete", lambda slug: {"expected_pages": 2})

    jobs_mod._run_book_generation_job(job_id, "demo", {"run_mode": "full"})

    job = jobs_mod.book_generation_jobs[job_id]
    assert job.status == "done"
    assert job.stage == "complete"
    assert job.progress == 100


def test_run_full_generation_build_errors_mark_failed(monkeypatch) -> None:
    job_id = _seed_job()
    monkeypatch.setattr(jobs_mod, "generate_book_from_dgx_brief", lambda *a, **k: [1])
    monkeypatch.setattr(jobs_mod, "generate_prompts_for_book", lambda *a, **k: ["p"])
    monkeypatch.setattr(jobs_mod, "export_page_specs_yaml", lambda *a, **k: ["s"])
    monkeypatch.setattr(jobs_mod, "build_book", lambda *a, **k: _build_result(errors=["boom"]))

    jobs_mod._run_book_generation_job(job_id, "demo", {"run_mode": "full"})

    job = jobs_mod.book_generation_jobs[job_id]
    assert job.status == "failed"
    assert "boom" in job.error


def test_run_page_image_reaches_done(monkeypatch) -> None:
    job_id = _seed_job()
    monkeypatch.setattr(jobs_mod, "get_book_by_slug", lambda s, slug: SimpleNamespace(id=1, slug=slug))
    monkeypatch.setattr(jobs_mod, "_page_for_book", lambda s, b, n: SimpleNamespace(page_number=n))
    monkeypatch.setattr(jobs_mod, "generate_page_prompt", lambda *a, **k: None)
    monkeypatch.setattr(jobs_mod, "export_page_spec_yaml", lambda *a, **k: None)
    monkeypatch.setattr(jobs_mod, "build_book", lambda *a, **k: _build_result())
    monkeypatch.setattr(jobs_mod, "_refresh_scene_image_from_page", lambda slug, n: 123)
    monkeypatch.setattr(jobs_mod, "_assert_page_image_generation_complete", lambda slug, n: {"page_number": n})

    jobs_mod._run_book_generation_job(job_id, "demo", {"run_mode": "page_image", "page_number": 5})

    job = jobs_mod.book_generation_jobs[job_id]
    assert job.status == "done"
    assert job.result.get("page_number") == 5


def test_run_single_character_reference_reaches_done(monkeypatch) -> None:
    job_id = _seed_job()
    monkeypatch.setattr(
        jobs_mod,
        "_generate_single_character_pack",
        lambda *a, **k: SimpleNamespace(ready=True, image_count=8, errors=[]),
    )

    jobs_mod._run_book_generation_job(
        job_id,
        "demo",
        {
            "run_mode": "single_character_reference",
            "character_name": "Firewall Fox",
            "character_slug": "firewall_fox",
        },
    )

    job = jobs_mod.book_generation_jobs[job_id]
    assert job.status == "done"
    assert job.result.get("character_reference_images") == 8


def test_run_character_reference_gate_failure_marks_failed(monkeypatch) -> None:
    job_id = _seed_job()
    monkeypatch.setattr(
        jobs_mod,
        "generate_character_reference_packs",
        lambda **k: SimpleNamespace(ready=False, errors=["qa failed"], character_count=0, image_count=0),
    )

    jobs_mod._run_book_generation_job(job_id, "demo", {"run_mode": "characters"})

    job = jobs_mod.book_generation_jobs[job_id]
    assert job.status == "failed"
    assert "qa failed" in job.error
