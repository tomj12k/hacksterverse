"""Tests for durable generation-job persistence (#2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlmodel import SQLModel, create_engine

from hackster_studio import database, job_store


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the job store at a throwaway SQLite DB for the test."""
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.sqlite3'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(database, "engine", engine)
    return engine


def test_persist_and_load_roundtrip(isolated_db) -> None:
    job_store.persist_job(
        {
            "job_id": "j1",
            "book_slug": "demo",
            "status": "running",
            "stage": "images",
            "progress": 42,
            "events": ["started", "midway"],
            "result": {"images": 3},
        }
    )
    loaded = job_store.load_job("j1")
    assert loaded is not None
    assert loaded["status"] == "running"
    assert loaded["progress"] == 42
    assert loaded["events"] == ["started", "midway"]
    assert loaded["result"] == {"images": 3}


def test_persist_is_upsert(isolated_db) -> None:
    job_store.persist_job({"job_id": "j2", "status": "queued", "progress": 4})
    job_store.persist_job({"job_id": "j2", "status": "done", "progress": 100})
    loaded = job_store.load_job("j2")
    assert loaded["status"] == "done"
    assert loaded["progress"] == 100


def test_load_missing_returns_none(isolated_db) -> None:
    assert job_store.load_job("nope") is None


def test_recover_orphaned_marks_unfinished_failed(isolated_db) -> None:
    job_store.persist_job({"job_id": "run", "status": "running", "progress": 50})
    job_store.persist_job({"job_id": "queued", "status": "queued", "progress": 4})
    job_store.persist_job({"job_id": "done", "status": "done", "progress": 100})

    recovered = job_store.recover_orphaned_jobs()
    assert recovered == 2
    assert job_store.load_job("run")["status"] == "failed"
    assert job_store.load_job("queued")["status"] == "failed"
    # Terminal jobs are untouched.
    assert job_store.load_job("done")["status"] == "done"


def test_persist_swallows_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    # A broken engine must not raise out of persist_job (best-effort mirror).
    monkeypatch.setattr(database, "engine", object())
    job_store.persist_job({"job_id": "x", "status": "running"})  # must not raise
