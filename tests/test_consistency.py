"""Tests for the cross-store consistency checker (#3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

from hackster_studio.models import Book, Page
from hackster_studio.services import consistency


@pytest.fixture
def session(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'c.sqlite3'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _make_book(session: Session, slug: str, page_count: int, db_pages: int) -> None:
    book = Book(title=slug, slug=slug, page_count=page_count)
    session.add(book)
    session.commit()
    session.refresh(book)
    for n in range(1, db_pages + 1):
        session.add(Page(book_id=book.id, page_number=n))
    session.commit()


def test_consistent_when_counts_align(session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(consistency, "BOOKS_DIR", tmp_path / "books")
    monkeypatch.setattr(consistency, "SCENES_DIR", tmp_path / "scenes")
    monkeypatch.setattr(consistency, "GENERATED_DIR", tmp_path / "gen")
    _make_book(session, "demo", page_count=2, db_pages=2)

    pages_dir = tmp_path / "books" / "demo" / "pages"
    pages_dir.mkdir(parents=True)
    for n in (1, 2):
        (pages_dir / f"page_{n:03d}.yaml").write_text("x")

    report = consistency.book_consistency_report(session, "demo")
    assert report["counts"]["db_pages"] == 2
    assert report["counts"]["yaml_pages"] == 2
    assert report["consistent"], report["drift"]


def test_drift_detected_when_yaml_missing(session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(consistency, "BOOKS_DIR", tmp_path / "books")
    monkeypatch.setattr(consistency, "SCENES_DIR", tmp_path / "scenes")
    monkeypatch.setattr(consistency, "GENERATED_DIR", tmp_path / "gen")
    _make_book(session, "demo", page_count=3, db_pages=3)
    # No YAML files written -> drift between DB (3) and YAML (0).

    report = consistency.book_consistency_report(session, "demo")
    assert not report["consistent"]
    assert any("YAML" in m for m in report["drift"])


def test_stale_surplus_artifacts_flagged(session, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(consistency, "BOOKS_DIR", tmp_path / "books")
    monkeypatch.setattr(consistency, "SCENES_DIR", tmp_path / "scenes")
    monkeypatch.setattr(consistency, "GENERATED_DIR", tmp_path / "gen")
    _make_book(session, "demo", page_count=1, db_pages=1)

    pages_dir = tmp_path / "books" / "demo" / "pages"
    pages_dir.mkdir(parents=True)
    (pages_dir / "page_001.yaml").write_text("x")
    illus = tmp_path / "books" / "demo" / "illustrations"
    illus.mkdir(parents=True)
    for n in (1, 2, 3):  # 3 illustrations but only 1 planned page
        (illus / f"page_{n:03d}.png").write_text("x")

    report = consistency.book_consistency_report(session, "demo")
    assert not report["consistent"]
    assert any("illustrations" in m for m in report["drift"])


def test_missing_book_raises(session) -> None:
    with pytest.raises(ValueError):
        consistency.book_consistency_report(session, "nope")
