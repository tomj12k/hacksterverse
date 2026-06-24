"""Page-level operations shared by HTTP routes and the job runners.

These helpers were previously defined in ``main.py``; they are extracted here
so both the request handlers and the background job runners can use them
without ``jobs.py`` having to import ``main`` (which would create a cycle).
"""

from __future__ import annotations

import json
from typing import Any

import yaml
from fastapi import HTTPException
from sqlmodel import Session, select

from .automation.build_book import build_book
from .automation.pipeline import BuildOptions
from .config import PROJECT_ROOT
from .models import Book, Page
from .services.story_maker import load_scene


def page_for_book(session: Session, book: Book, page_number: int) -> Page:
    if book.id is None:
        raise ValueError(f"Book not saved: {book.slug}")
    page = session.exec(
        select(Page).where(Page.book_id == book.id, Page.page_number == page_number)
    ).first()
    if page is None:
        raise HTTPException(status_code=404, detail=f"Page {page_number} not found for {book.slug}")
    return page


def nearby_page_context(session: Session, book: Book, page_number: int) -> dict[str, Any]:
    def summarize(page: Page | None) -> dict[str, Any]:
        if page is None:
            return {}
        return {
            "page_number": page.page_number,
            "page_type": page.page_type,
            "scene_title": page.scene_title,
            "story_text": page.story_text[:500],
            "illustration_direction": page.illustration_direction[:500],
            "characters": json.loads(page.characters_json or "[]"),
            "environment": page.environment,
        }

    if book.id is None:
        return {}
    pages = {
        item.page_number: item
        for item in session.exec(
            select(Page).where(
                Page.book_id == book.id,
                Page.page_number.in_([page_number - 1, page_number, page_number + 1]),
            )
        ).all()
    }
    return {
        "previous_page": summarize(pages.get(page_number - 1)),
        "current_page": summarize(pages.get(page_number)),
        "next_page": summarize(pages.get(page_number + 1)),
    }


def refresh_scene_text_from_page(book_slug: str, page_number: int, story_text: str) -> None:
    from .services.story_maker import save_scene

    scene = load_scene(book_slug, page_number)
    scene["story_text"] = story_text
    scene["scene_title"] = book_page_title(book_slug, page_number)
    for layer in scene.get("layers", []):
        if layer.get("id") == "page_text" or layer.get("type") == "text":
            layer["text"] = story_text
            layer["name"] = story_text.strip()[:36] or "Page Text"
            layer["asset_path"] = None
            break
    save_scene(scene)


def refresh_scene_image_from_page(book_slug: str, page_number: int) -> int | None:
    from .services.story_maker import (
        book_illustration_asset_path,
        book_illustration_asset_version,
        review_image_layer,
        save_scene,
    )

    scene = load_scene(book_slug, page_number)
    illustration = book_illustration_asset_path(book_slug, page_number)
    illustration_version = book_illustration_asset_version(book_slug, page_number)
    if not illustration:
        save_scene(scene)
        return illustration_version

    layers = scene.setdefault("layers", [])
    image_layer = next((layer for layer in layers if layer.get("id") == "book_illustration"), None)
    if image_layer is None:
        layers.insert(0, review_image_layer(illustration, asset_version=illustration_version))
    else:
        image_layer["name"] = "Current Page Illustration"
        image_layer["type"] = "background"
        image_layer["asset_path"] = illustration
        image_layer["locked"] = True
        image_layer["z_index"] = 0
        image_layer["asset_version"] = illustration_version
        image_layer.setdefault("transform", review_image_layer(illustration)["transform"])
    scene["book_illustration_path"] = illustration
    if illustration_version is not None:
        scene["book_illustration_version"] = illustration_version
    scene["status"] = "generated"
    save_scene(scene)
    return illustration_version


def refresh_book_page_prompt_package(book_slug: str, page_number: int) -> None:
    build_book(
        PROJECT_ROOT / "books" / book_slug / "book.yaml",
        BuildOptions(
            generate_images=False,
            image_backend="comfyui",
            build_pdf=False,
            build_production_pdf=False,
            build_idml=False,
            force=False,
            page_from=page_number,
            page_to=page_number,
            skip_production_gate=True,
            manage_dgx_image_profile=False,
        ),
    )


def book_page_title(book_slug: str, page_number: int) -> str:
    metadata_path = PROJECT_ROOT / "books" / book_slug / "pages" / f"page_{page_number:03d}.yaml"
    if not metadata_path.exists():
        return f"Page {page_number}"
    data = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
    return str(data.get("scene_title") or f"Page {page_number}")
