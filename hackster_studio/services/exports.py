"""Export production data from the database."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from sqlmodel import Session, select

from ..config import GENERATED_DIR, PROJECT_ROOT
from ..models import Book, Page


def export_page_specs_yaml(session: Session, book_slug: str) -> list[Path]:
    book = session.exec(select(Book).where(Book.slug == book_slug)).first()
    if book is None:
        raise ValueError(f"Book not found: {book_slug}. Run seed first.")

    pages = list(session.exec(select(Page).where(Page.book_id == book.id).order_by(Page.page_number)).all())
    if not pages:
        raise ValueError(f"No pages found for {book_slug}. Run plan-book first.")

    output_dir = GENERATED_DIR / "page_specs" / book_slug
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths: list[Path] = []

    for page in pages:
        output_paths.append(write_page_spec_yaml(book, page, output_dir=output_dir))

    return output_paths


def export_page_spec_yaml(session: Session, book_slug: str, page_number: int) -> Path:
    book = session.exec(select(Book).where(Book.slug == book_slug)).first()
    if book is None or book.id is None:
        raise ValueError(f"Book not found: {book_slug}.")
    page = session.exec(
        select(Page).where(Page.book_id == book.id, Page.page_number == page_number)
    ).first()
    if page is None:
        raise ValueError(f"Page {page_number} not found for {book_slug}.")
    return write_page_spec_yaml(book, page)


def write_page_spec_yaml(book: Book, page: Page, *, output_dir: Path | None = None) -> Path:
    output_dir = output_dir or GENERATED_DIR / "page_specs" / book.slug
    output_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "book": book.title,
        "book_slug": book.slug,
        "page_number": page.page_number,
        "page_type": page.page_type,
        "scene_title": page.scene_title,
        "story_text": page.story_text,
        "illustration_direction": page.illustration_direction,
        "characters": json.loads(page.characters_json or "[]"),
        "environment": page.environment,
        "emotion": page.emotion,
        "camera": page.camera,
        "hidden_objects": json.loads(page.hidden_objects_json or "[]"),
        "text_safe_area": page.text_safe_area,
        "illustration_path": page.illustration_path,
        "prompt_path": page.prompt_path,
        "status": page.status,
    }
    output_path = output_dir / f"page_{page.page_number:02d}.yaml"
    output_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="utf-8")
    return output_path


def relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()
