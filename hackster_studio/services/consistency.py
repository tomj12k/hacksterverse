"""Cross-store consistency checks for a book's page data.

A page exists in several independent representations that can silently drift:

* the SQLite ``Page`` rows (planning source of truth),
* ``books/<slug>/pages/page_NNN.yaml`` (read by the build pipeline),
* ``books/<slug>/prompts/page_NNN.md`` and ``illustrations/page_NNN.png``,
* ``storybook_scenes/<slug>/page_NNN.scene.json`` (the editor),
* ``data/generated/page_specs/<slug>/page_NN.yaml``.

This module does not change how those are written; it reports where they
disagree so drift is visible instead of surfacing later as a wrong page count
or a missing illustration. The ``Page`` table is treated as the reference.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlmodel import Session

from ..config import BOOKS_DIR, GENERATED_DIR, SCENES_DIR
from .books import get_book_by_slug, get_pages_for_book


def _count_glob(directory: Path, pattern: str) -> int:
    if not directory.exists():
        return 0
    return sum(1 for _ in directory.glob(pattern))


def book_consistency_report(session: Session, book_slug: str) -> dict[str, Any]:
    """Compare a book's page representations and report any drift.

    :returns: a dict with per-store counts, a ``consistent`` flag, and a list
        of human-readable ``drift`` messages.
    :rtype: dict
    """
    book = get_book_by_slug(session, book_slug)
    if book is None or book.id is None:
        raise ValueError(f"Book not found: {book_slug}")

    declared = int(book.page_count or 0)
    db_pages = len(get_pages_for_book(session, book.id))

    book_root = BOOKS_DIR / book_slug
    counts = {
        "declared_page_count": declared,
        "db_pages": db_pages,
        "yaml_pages": _count_glob(book_root / "pages", "page_*.yaml"),
        "prompts": _count_glob(book_root / "prompts", "page_*.md"),
        "illustrations": _count_glob(book_root / "illustrations", "page_*.png"),
        "scene_files": _count_glob(SCENES_DIR / book_slug, "page_*.scene.json"),
        "page_specs": _count_glob(GENERATED_DIR / "page_specs" / book_slug, "page_*.yaml"),
    }

    drift: list[str] = []
    if declared and db_pages != declared:
        drift.append(f"DB has {db_pages} pages but book.page_count is {declared}.")
    # The on-disk YAML is what the build pipeline reads; it should match the DB.
    if counts["yaml_pages"] != db_pages:
        drift.append(f"{counts['yaml_pages']} page YAML files on disk vs {db_pages} DB rows.")
    # Prompts/illustrations may legitimately lag during generation; only flag a
    # surplus (more artifacts than planned pages), which signals stale files.
    for label in ("prompts", "illustrations", "scene_files", "page_specs"):
        if db_pages and counts[label] > db_pages:
            drift.append(f"{counts[label]} {label} exceed {db_pages} planned pages (stale files?).")

    return {
        "book_slug": book_slug,
        "counts": counts,
        "consistent": not drift,
        "drift": drift,
    }
