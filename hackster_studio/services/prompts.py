"""Prompt generation for characters, environments, gadgets, and book pages."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jinja2 import Environment as JinjaEnvironment
from jinja2 import FileSystemLoader
from sqlmodel import Session, select

from ..config import GENERATED_DIR, PROJECT_ROOT
from ..models import Book, Character, Environment, Gadget, Page, Prompt
from ..services.characters import NIKO_CONSISTENCY_PHRASE


PROMPT_TEMPLATE_DIR = PROJECT_ROOT / "hackster_studio" / "prompt_templates"


def jinja_environment() -> JinjaEnvironment:
    return JinjaEnvironment(
        loader=FileSystemLoader(PROMPT_TEMPLATE_DIR),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _slugify_filename(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug[:48] or "untitled"


def _write_prompt(
    session: Session,
    *,
    prompt_type: str,
    related_type: str,
    related_id: int,
    title: str,
    prompt_text: str,
    output_path: Path,
) -> Prompt:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(prompt_text.rstrip() + "\n", encoding="utf-8")

    prompt = session.exec(
        select(Prompt).where(
            Prompt.prompt_type == prompt_type,
            Prompt.related_type == related_type,
            Prompt.related_id == related_id,
        )
    ).first()
    if prompt is None:
        prompt = Prompt(
            prompt_type=prompt_type,
            related_type=related_type,
            related_id=related_id,
            output_path=_relative(output_path),
        )

    prompt.title = title
    prompt.prompt_text = prompt_text
    prompt.status = "generated"
    session.add(prompt)
    session.commit()
    session.refresh(prompt)
    return prompt


def generate_character_prompt(session: Session, character: Character) -> Prompt:
    template = jinja_environment().get_template("character_reference.md.j2")
    prompt_text = template.render(character=character)
    output_path = GENERATED_DIR / "prompts" / "characters" / f"{character.slug}.character_reference.md"
    return _write_prompt(
        session,
        prompt_type="character_reference",
        related_type="character",
        related_id=character.id or 0,
        title=f"{character.name} Character Reference",
        prompt_text=prompt_text,
        output_path=output_path,
    )


def generate_environment_prompt(session: Session, environment_model: Environment) -> Prompt:
    template = jinja_environment().get_template("environment_reference.md.j2")
    prompt_text = template.render(environment=environment_model)
    output_path = GENERATED_DIR / "prompts" / "environments" / f"{environment_model.slug}.environment_reference.md"
    return _write_prompt(
        session,
        prompt_type="environment_reference",
        related_type="environment",
        related_id=environment_model.id or 0,
        title=f"{environment_model.name} Environment Reference",
        prompt_text=prompt_text,
        output_path=output_path,
    )


def generate_gadget_prompt(session: Session, gadget: Gadget) -> Prompt:
    template = jinja_environment().get_template("gadget_reference.md.j2")
    prompt_text = template.render(gadget=gadget)
    output_path = GENERATED_DIR / "prompts" / "gadgets" / f"{gadget.slug}.gadget_reference.md"
    return _write_prompt(
        session,
        prompt_type="gadget_reference",
        related_type="gadget",
        related_id=gadget.id or 0,
        title=f"{gadget.name} Gadget Reference",
        prompt_text=prompt_text,
        output_path=output_path,
    )


def page_context(session: Session, page: Page) -> dict[str, Any]:
    book = session.get(Book, page.book_id)
    characters = json.loads(page.characters_json or "[]")
    hidden_objects = json.loads(page.hidden_objects_json or "[]")
    return {
        "book": book,
        "page": page,
        "characters": characters,
        "hidden_objects": hidden_objects,
        "niko_consistency_phrase": NIKO_CONSISTENCY_PHRASE,
    }


def generate_page_prompt(session: Session, page: Page) -> Prompt:
    template = jinja_environment().get_template("book_page_illustration.md.j2")
    context = page_context(session, page)
    prompt_text = template.render(**context)
    book = context["book"]
    book_slug = book.slug if book else "unknown_book"
    output_path = (
        GENERATED_DIR
        / "prompts"
        / "pages"
        / book_slug
        / f"page_{page.page_number:02d}_{_slugify_filename(page.scene_title)}.md"
    )
    prompt = _write_prompt(
        session,
        prompt_type="book_page_illustration",
        related_type="page",
        related_id=page.id or 0,
        title=f"Page {page.page_number:02d}: {page.scene_title}",
        prompt_text=prompt_text,
        output_path=output_path,
    )
    page.prompt_path = prompt.output_path
    page.status = "prompt generated"
    session.add(page)
    session.commit()
    return prompt


def generate_prompts_for_book(session: Session, book_slug: str) -> list[Prompt]:
    book = session.exec(select(Book).where(Book.slug == book_slug)).first()
    if book is None:
        raise ValueError(f"Book not found: {book_slug}. Run seed first.")

    pages = list(session.exec(select(Page).where(Page.book_id == book.id).order_by(Page.page_number)).all())
    if not pages:
        raise ValueError(f"No pages found for {book_slug}. Run plan-book first.")

    prompt_ids: list[int] = []
    for page in pages:
        prompt = generate_page_prompt(session, page)
        if prompt.id is not None:
            prompt_ids.append(prompt.id)

    prompts: list[Prompt] = []
    for prompt_id in prompt_ids:
        prompt = session.get(Prompt, prompt_id)
        if prompt is not None:
            session.refresh(prompt)
            prompts.append(prompt)
    return prompts


def list_prompts(session: Session) -> list[Prompt]:
    return list(session.exec(select(Prompt).order_by(Prompt.created_at.desc())).all())
