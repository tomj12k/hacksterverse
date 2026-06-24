"""Durable persistence for book-generation jobs (write-through mirror).

The live state lives in an in-memory dict for speed; this module mirrors each
update into the ``GenerationJob`` SQLite table so job status survives a server
restart and orphaned jobs can be recovered on startup.

All functions open their own short-lived ``Session`` so they are safe to call
from the executor's worker threads.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from . import database
from .models import GenerationJob

# Statuses considered "not finished". After a restart the in-memory state is
# gone, so any row left in one of these is an orphan and gets marked failed.
_UNFINISHED = ("queued", "running")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def persist_job(snapshot: dict[str, Any]) -> None:
    """Upsert a job payload (as produced by ``_book_generation_job_payload``).

    Best-effort: persistence must never break the live job, so DB errors are
    swallowed (the in-memory store remains the source of truth).
    """
    try:
        with Session(database.engine) as session:
            row = session.get(GenerationJob, snapshot["job_id"])
            if row is None:
                row = GenerationJob(job_id=str(snapshot["job_id"]))
                session.add(row)
            row.book_slug = str(snapshot.get("book_slug", ""))
            row.redirect_url = str(snapshot.get("redirect_url", ""))
            row.status = str(snapshot.get("status", "queued"))
            row.stage = str(snapshot.get("stage", "queued"))
            row.progress = int(snapshot.get("progress", 0))
            row.error = str(snapshot.get("error", ""))
            row.events_json = json.dumps(list(snapshot.get("events", [])))
            row.result_json = json.dumps(dict(snapshot.get("result", {})))
            row.updated_at = _now()
            session.commit()
    except Exception:
        # Intentionally broad: a persistence failure (locked DB, disk full)
        # must not take down an in-flight generation. The in-memory store still
        # serves live status; we simply lose restart-durability for this update.
        import logging

        logging.getLogger(__name__).warning("Failed to persist job %s", snapshot.get("job_id"), exc_info=True)


def load_job(job_id: str) -> dict[str, Any] | None:
    """Return a job payload dict from the DB, or None if absent."""
    with Session(database.engine) as session:
        row = session.get(GenerationJob, job_id)
        if row is None:
            return None
        return _row_to_payload(row)


def recover_orphaned_jobs() -> int:
    """Mark queued/running rows as failed (their in-memory state is gone).

    Called on startup. Returns the number of jobs recovered.
    """
    recovered = 0
    with Session(database.engine) as session:
        rows = session.exec(select(GenerationJob).where(GenerationJob.status.in_(_UNFINISHED))).all()
        for row in rows:
            row.status = "failed"
            row.stage = "failed"
            row.error = "Server restarted while this job was in progress."
            row.updated_at = _now()
            session.add(row)
            recovered += 1
        if recovered:
            session.commit()
    return recovered


def _row_to_payload(row: GenerationJob) -> dict[str, Any]:
    try:
        events = json.loads(row.events_json or "[]")
    except json.JSONDecodeError:
        events = []
    try:
        result = json.loads(row.result_json or "{}")
    except json.JSONDecodeError:
        result = {}
    return {
        "job_id": row.job_id,
        "book_slug": row.book_slug,
        "redirect_url": row.redirect_url,
        "status": row.status,
        "stage": row.stage,
        "progress": row.progress,
        "events": events,
        "error": row.error,
        "result": result,
    }
