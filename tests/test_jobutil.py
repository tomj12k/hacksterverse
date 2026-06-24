"""Tests for bounded in-memory job stores (A-3)."""

from __future__ import annotations

from hackster_studio.jobutil import MAX_TRACKED_JOBS, evict_oldest


def test_evict_oldest_caps_and_keeps_newest() -> None:
    store = {i: f"v{i}" for i in range(10)}
    evict_oldest(store, max_items=5)
    assert len(store) == 5
    # Oldest (0-4) dropped, newest (5-9) retained.
    assert set(store) == {5, 6, 7, 8, 9}


def test_evict_oldest_noop_when_under_cap() -> None:
    store = {1: "a", 2: "b"}
    evict_oldest(store, max_items=5)
    assert store == {1: "a", 2: "b"}


def test_evict_oldest_default_cap_is_reasonable() -> None:
    assert MAX_TRACKED_JOBS >= 50


def test_book_generation_job_store_stays_bounded() -> None:
    import hackster_studio.main as main_mod

    store = main_mod._book_generation_jobs
    # Simulate the insertion+evict the route performs, beyond the cap.
    for index in range(MAX_TRACKED_JOBS + 25):
        store[f"job-{index}"] = object()
        evict_oldest(store)
    assert len(store) <= MAX_TRACKED_JOBS
    # Clean up so we don't perturb other tests sharing the module global.
    store.clear()


def test_start_book_generation_runs_via_executor(monkeypatch) -> None:
    """#4: jobs run on the managed ThreadPoolExecutor, not ad-hoc daemon threads."""
    import threading

    import hackster_studio.jobs as jobs_mod
    import hackster_studio.main as main_mod

    ran = threading.Event()
    captured: dict[str, object] = {}

    def fake_run(job_id: str, book_slug: str, payload: dict) -> None:
        captured["job_id"] = job_id
        captured["book_slug"] = book_slug
        ran.set()

    # The runner lives in .jobs; start_book_generation_job (also in .jobs)
    # submits jobs_mod._run_book_generation_job to the executor.
    monkeypatch.setattr(jobs_mod, "_run_book_generation_job", fake_run)
    job = main_mod.start_book_generation_job("demo_book", {"run_mode": "x"})
    assert ran.wait(timeout=5), "executor did not run the submitted job"
    assert captured["job_id"] == job.job_id
    assert captured["book_slug"] == "demo_book"
    jobs_mod.book_generation_jobs.clear()
