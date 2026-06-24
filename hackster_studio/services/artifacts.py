"""Filesystem artifact counting for a book's on-disk page outputs.

Pure helpers (no DB, no app state) that count the page YAML/prompt/image/review
files a build produces. Extracted from ``main.py`` so both the job runners and
the HTTP routes can share one implementation.
"""

from __future__ import annotations

from pathlib import Path

from ..config import PROJECT_ROOT


def count_page_files(directory: Path, pattern: str, page_count: int) -> int:
    """Count files matching ``pattern`` for page numbers 1..page_count."""
    return sum(
        1
        for page_number in range(1, page_count + 1)
        if (directory / pattern.format(page_number)).exists()
    )


def first_missing_image_page(book_slug: str, page_count: int) -> int | None:
    """Return the first page number with no illustration PNG, or None."""
    for page_number in range(1, page_count + 1):
        if not (PROJECT_ROOT / "books" / book_slug / "illustrations" / f"page_{page_number:03d}.png").exists():
            return page_number
    return None


def book_artifact_counts(book_slug: str, page_count: int) -> dict[str, int]:
    """Count every on-disk artifact kind for a book, keyed by stage."""
    root = PROJECT_ROOT / "books" / book_slug
    generated = PROJECT_ROOT / "data" / "generated"
    return {
        "expected_pages": page_count,
        "pages": count_page_files(root / "pages", "page_{:03d}.yaml", page_count),
        "book_prompts": count_page_files(root / "prompts", "page_{:03d}.md", page_count),
        "generated_prompts": len(list((generated / "prompts" / "pages" / book_slug).glob("*.md"))),
        "page_specs": count_page_files(generated / "page_specs" / book_slug, "page_{:02d}.yaml", page_count),
        "images": count_page_files(root / "illustrations", "page_{:03d}.png", page_count),
        "reviews": count_page_files(root / "review", "page_{:03d}_review.md", page_count),
    }
