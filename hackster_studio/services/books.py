"""Book planning and seed data services."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Callable

from sqlmodel import Session, select
import yaml

from ..config import GENERATED_DIR, LAYERS_DIR, PROJECT_ROOT
from ..pathsafe import is_within_any
from ..models import Book, Page, Project, Prompt, utc_now


STORY_BEATS = [
    "Niko enters Cyber Forest.",
    "Password Dragon sneezes passwords everywhere.",
    "Niko comforts the dragon.",
    "Niko explains that easy passwords are weak.",
    "They build a silly strong password.",
    "Guessing Goblins try easy guesses and fail.",
    "Password Parrot almost repeats the secret.",
    "Niko explains secrets should stay secret.",
    "They build a Password Vault.",
    "The forest celebrates.",
    "A suspicious email teaser hints at Book 2: Sneaky Phish.",
]
GENERIC_STORY_BEATS = [
    "The hero discovers a small problem that feels enormous.",
    "A friend arrives with a surprising idea.",
    "The team studies the clues and chooses a kind first step.",
    "The first attempt goes sideways in a funny, harmless way.",
    "A hidden detail helps everyone understand what is missing.",
    "The hero listens, tries again, and improves the plan.",
    "The team solves the problem together.",
    "Everyone celebrates the lesson and sets up the next adventure.",
]

HIDDEN_OBJECTS = ["Golden Gear", "Tiny Bug", "Blue Crystal", "Mini Robot"]
DEFAULT_FOCUS_CHARACTERS = ["Hackster Niko", "Helpful Friend", "Lesson Guide"]
GENERIC_FOCUS_CHARACTERS = ["Main Character", "Helpful Friend", "Comic Sidekick"]


BOOK_DIRS = [
    "pages",
    "prompts",
    "illustrations",
    "illustrations_locked",
    "review",
    "reports",
    "exports/lulu",
    "exports/affinity",
    "affinity_package",
    "pdf",
    "qa_candidates",
    "qa_rejected",
]


def slugify_book_title(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return slug or "untitled_book"


def list_books(session: Session) -> list[Book]:
    return list(session.exec(select(Book).order_by(Book.title)).all())


def get_book_by_slug(session: Session, slug: str) -> Book | None:
    return session.exec(select(Book).where(Book.slug == slug)).first()


def get_pages_for_book(session: Session, book_id: int) -> list[Page]:
    return list(
        session.exec(select(Page).where(Page.book_id == book_id).order_by(Page.page_number)).all()
    )


def delete_book(session: Session, book_slug: str) -> dict[str, Any]:
    book = get_book_by_slug(session, book_slug)
    if book is None or book.id is None:
        raise ValueError(f"Book not found: {book_slug}")

    pages = get_pages_for_book(session, book.id)
    page_ids = [page.id for page in pages if page.id is not None]
    if page_ids:
        prompts = session.exec(
            select(Prompt).where(Prompt.related_type == "page", Prompt.related_id.in_(page_ids))
        ).all()
        for prompt in prompts:
            session.delete(prompt)
    for page in pages:
        session.delete(page)
    session.delete(book)
    session.commit()

    removed_paths = remove_book_files(book_slug)
    return {"slug": book_slug, "removed_paths": removed_paths}


def remove_book_files(book_slug: str) -> list[str]:
    removed: list[str] = []
    candidate_dirs = [
        PROJECT_ROOT / "books" / book_slug,
        GENERATED_DIR / "page_specs" / book_slug,
        GENERATED_DIR / "prompts" / "pages" / book_slug,
        GENERATED_DIR / "pages" / book_slug,
        GENERATED_DIR / "reports" / book_slug,
        GENERATED_DIR / "manifests" / book_slug,
        _scene_root() / book_slug,
        LAYERS_DIR / "text" / book_slug,
    ]
    for path in candidate_dirs:
        if _remove_tree(path):
            removed.append(path.as_posix())

    for path in _book_character_layer_files(book_slug):
        if _remove_file(path):
            removed.append(path.as_posix())
    return removed


def _scene_root() -> Path:
    return Path(os.getenv("HACKSTER_SCENE_ROOT", PROJECT_ROOT / "storybook_scenes"))


def _book_character_layer_files(book_slug: str) -> list[Path]:
    characters_dir = LAYERS_DIR / "characters"
    if not characters_dir.exists():
        return []
    matches: list[Path] = []
    for custom_dir in characters_dir.glob("*/custom"):
        for extension in ("png", "jpg", "jpeg", "webp"):
            matches.extend(custom_dir.glob(f"{book_slug}*.{extension}"))
    return sorted(path for path in matches if path.is_file())


def _remove_tree(path: Path) -> bool:
    path = path.resolve()
    if not _is_safe_project_path(path) or not path.exists():
        return False
    if path.is_dir():
        shutil.rmtree(path)
        return True
    path.unlink()
    return True


def _remove_file(path: Path) -> bool:
    path = path.resolve()
    if not _is_safe_project_path(path) or not path.exists() or not path.is_file():
        return False
    path.unlink()
    return True


def _is_safe_project_path(path: Path) -> bool:
    # Strictly nested under a root — a path equal to a root (e.g. a slug that
    # resolves to PROJECT_ROOT via "..") is NOT safe and must never be deleted.
    roots = [PROJECT_ROOT.resolve(), _scene_root().resolve()]
    return is_within_any(path, roots)


def ensure_unique_slug(session: Session, slug: str) -> str:
    base = slugify_book_title(slug)
    candidate = base
    index = 2
    while get_book_by_slug(session, candidate):
        candidate = f"{base}_{index}"
        index += 1
    return candidate


def create_book(
    session: Session,
    *,
    title: str,
    slug: str = "",
    series: str = "Hackster Niko",
    target_age: str = "5-8",
    lesson: str = "",
    page_count: int = 32,
    trim_size: str = "8.5x8.5",
) -> Book:
    clean_title = title.strip() or "Untitled Hackster Niko Book"
    clean_slug = ensure_unique_slug(session, slug or clean_title)
    book = Book(
        title=clean_title,
        slug=clean_slug,
        series=series.strip() or "Hackster Niko",
        target_age=target_age.strip() or "5-8",
        lesson=lesson.strip(),
        page_count=max(1, min(96, int(page_count or 32))),
        trim_size=trim_size.strip() or "8.5x8.5",
        status="created",
        updated_at=utc_now(),
    )
    session.add(book)
    session.commit()
    session.refresh(book)
    ensure_book_files(session, book)
    return book


def ensure_book_files(session: Session, book: Book) -> None:
    root = PROJECT_ROOT / "books" / book.slug
    for dirname in BOOK_DIRS:
        (root / dirname).mkdir(parents=True, exist_ok=True)
    write_book_yaml(book)
    ensure_book_pages(session, book)


def write_book_yaml(book: Book) -> Path:
    root = PROJECT_ROOT / "books" / book.slug
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "title": book.title,
        "series": book.series,
        "slug": book.slug,
        "trim_size": book.trim_size,
        "page_count": book.page_count,
        "target_age": book.target_age,
        "lesson": book.lesson,
        "niko_layer_mode": "posable_layer" if book_is_hackster_niko(book) else "none",
        "character_layer_mode": "separate_layers",
        "bleed_inches": 0.125,
        "safe_margin_inches": 0.5,
        "dpi": 300,
        "global_illustration_style": (
            "premium dimensional children's picture book illustration, bright and warm, "
            "rounded friendly shapes, soft cinematic lighting, saturated colors, "
            "no text baked into image, leave clean open space for editable story text."
        ),
        "hidden_objects": HIDDEN_OBJECTS,
        "story_beats": STORY_BEATS if book_is_hackster_niko(book) else GENERIC_STORY_BEATS,
    }
    brief = read_planning_brief(book.slug)
    if brief:
        payload["planner_brief"] = brief
    path = root / "book.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def planning_brief_path(book_slug: str) -> Path:
    return PROJECT_ROOT / "books" / book_slug / "planning_brief.yaml"


def read_planning_brief(book_slug: str) -> dict[str, Any]:
    path = planning_brief_path(book_slug)
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def write_planning_brief(
    book: Book,
    *,
    idea: str,
    focus_characters: list[str],
    focus_items: list[str],
    reference_notes: str,
) -> Path:
    path = planning_brief_path(book.slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "idea": idea,
        "focus_characters": focus_characters,
        "focus_items": focus_items,
        "reference_notes": reference_notes,
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def split_focus_list(value: str, fallback: list[str], count: int) -> list[str]:
    raw = [
        item.strip()
        for item in re.split(r"[,;\n]+", value or "")
        if item.strip()
    ]
    items = raw or fallback
    target = max(1, min(12, int(count or len(items) or 1)))
    while len(items) < target:
        items.append(fallback[(len(items) - 1) % len(fallback)])
    return items[:target]


def book_is_hackster_niko(book: Book) -> bool:
    return "hackster niko" in book.title.lower()


def should_include_hackster_niko(book: Book, characters: str = "") -> bool:
    raw = characters.lower()
    return book_is_hackster_niko(book) or "hackster niko" in raw


def focus_character_defaults(book: Book) -> list[str]:
    return DEFAULT_FOCUS_CHARACTERS if book_is_hackster_niko(book) else GENERIC_FOCUS_CHARACTERS


def clean_idea(idea: str, book: Book) -> str:
    if idea.strip():
        return idea.strip()
    if book_is_hackster_niko(book):
        return f"{book.title}: a friendly Hackster Niko adventure that teaches {book.lesson or 'a useful technology lesson'}."
    return f"{book.title}: a friendly story that teaches {book.lesson or 'a useful lesson'}."


def short_text(value: object, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def idea_phrase(idea: str) -> str:
    phrase = re.split(r"[.!?]\s+", idea.strip(), maxsplit=1)[0].strip()
    return phrase[:170] or "a friendly learning adventure"


def generated_story_beats(idea: str, focus_items: list[str]) -> list[str]:
    core = idea_phrase(idea)
    first_item = focus_items[0] if focus_items else "a helpful clue"
    second_item = focus_items[1] if len(focus_items) > 1 else "a glowing tool"
    return [
        f"The hero discovers the problem: {core}.",
        "The hero meets a friend who explains why the problem matters.",
        f"The team finds {first_item} and asks curious questions.",
        f"A first clever fix almost works, but something is missing.",
        f"The group uses {second_item} to test a kinder solution.",
        "Everyone shares ideas and turns a mistake into a clue.",
        "The hero helps the team build the final clever fix.",
        "The lesson clicks, the world brightens, and the friends celebrate.",
    ]


def generated_page_payload(
    book: Book,
    page_number: int,
    *,
    idea: str,
    focus_characters: list[str],
    focus_items: list[str],
    reference_notes: str,
) -> dict[str, Any]:
    title = book.title
    uses_niko = book_is_hackster_niko(book) or any(character.strip() == "Hackster Niko" for character in focus_characters)
    characters = (
        ["Hackster Niko", *[c for c in focus_characters if c != "Hackster Niko"]]
        if uses_niko
        else [c for c in focus_characters if c.strip()]
    )
    hidden = focus_items or HIDDEN_OBJECTS
    brief = idea_phrase(idea)
    page_count = book.page_count
    story_start = 4 if page_count >= 8 else 2
    story_end = max(story_start, page_count - 3)
    beats = generated_story_beats(idea, hidden)
    reference = f" Reference notes: {reference_notes}" if reference_notes.strip() else ""

    if page_number == 1:
        return {
            "page_type": "front_matter",
            "scene_title": "Title Page",
            "story_text": title,
            "illustration_direction": (
                f"Premium title-page composition for {title}. Show the main characters and visual clues for: {brief}."
                f" Feature reference characters: {', '.join(characters)}.{reference}"
            ),
            "characters": characters[:2],
            "environment": "Story world entrance",
            "emotion": "wonder",
            "camera": "hero title-page view",
            "hidden_objects": hidden[:2],
            "text_safe_area": "Large clean title area; keep all text editable.",
            "status": "planned",
        }
    if page_number == 2 and page_count >= 8:
        return {
            "page_type": "front_matter",
            "scene_title": "Copyright",
            "story_text": "Copyright and publishing details.",
            "illustration_direction": "Quiet production-safe copyright page with a small story-themed mark and soft pattern.",
            "characters": [],
            "environment": "",
            "emotion": "calm",
            "camera": "minimal layout",
            "hidden_objects": [],
            "text_safe_area": "Keep most of the page open for editable copyright text.",
            "status": "planned",
        }
    if page_number == 3 and page_count >= 8:
        return {
            "page_type": "front_matter",
            "scene_title": "Dedication",
            "story_text": "Dedication text placeholder.",
            "illustration_direction": f"Gentle dedication vignette with {characters[0] if characters else 'the hero'}, {characters[-1] if len(characters) > 1 else 'a friend'}, and one important object.",
            "characters": characters[:2],
            "environment": "",
            "emotion": "kind",
            "camera": "quiet vignette",
            "hidden_objects": hidden[:1],
            "text_safe_area": "Leave clean open center area for dedication text.",
            "status": "planned",
        }
    if page_number > story_end:
        if page_number == page_count - 2:
            return {
                "page_type": "ending",
                "scene_title": "The Clever Fix",
                "story_text": "Every problem has a clever fix!",
                "illustration_direction": f"Warm celebration showing the solved problem from the book idea: {brief}.",
                "characters": characters,
                "environment": "Resolved story world",
                "emotion": "celebration",
                "camera": "wide joyful finale",
                "hidden_objects": hidden,
                "text_safe_area": "Leave open space for the catchphrase as editable text.",
                "status": "planned",
            }
        if page_number == page_count - 1:
            return {
                "page_type": "activity",
                "scene_title": "Try The Fix",
                "story_text": "Activity page: draw or write your own clever fix with a trusted grown-up.",
                "illustration_direction": f"Activity worksheet layout using objects from the story: {', '.join(hidden)}.",
                "characters": characters[:1],
                "environment": "",
                "emotion": "encouraging",
                "camera": "activity page layout",
                "hidden_objects": hidden[:2],
                "text_safe_area": "Leave large editable worksheet zones.",
                "status": "planned",
            }
        return {
            "page_type": "teaser",
            "scene_title": "Next Adventure Teaser",
            "story_text": "A new clue glowed nearby. Another clever fix was waiting.",
            "illustration_direction": "Friendly teaser page with a non-scary clue for the next adventure.",
            "characters": characters[:1],
            "environment": "Story world",
            "emotion": "curious",
            "camera": "teaser close-up",
            "hidden_objects": hidden[-2:] if len(hidden) >= 2 else hidden,
            "text_safe_area": "Leave clean open area for teaser copy.",
            "status": "planned",
        }

    story_index = max(0, page_number - story_start)
    story_pages = max(1, story_end - story_start + 1)
    beat = beats[min(len(beats) - 1, int(story_index / story_pages * len(beats)))]
    featured_item = hidden[story_index % len(hidden)] if hidden else "a clue"
    featured_character = characters[story_index % len(characters)] if characters else "the hero"
    return {
        "page_type": "story",
        "scene_title": beat,
        "story_text": f"Draft page {page_number}: {beat.rstrip('.')}.",
        "illustration_direction": (
            f"Show {beat.lower()} Keep the page bright, dimensional, friendly, and readable."
            f" Feature {featured_character} and {featured_item}. Do not bake in text.{reference}"
        ),
        "characters": list(dict.fromkeys(([featured_character] if not uses_niko else ["Hackster Niko", featured_character]))),
        "environment": "Generated story world",
        "emotion": ["curious", "surprised", "caring", "confident", "playful", "relieved"][story_index % 6],
        "camera": ["wide establishing shot", "medium storybook view", "close warm character moment"][story_index % 3],
        "hidden_objects": hidden,
        "text_safe_area": "Leave clean open space for editable story text inside safe margins.",
        "status": "planned",
    }


def ensure_book_pages(session: Session, book: Book) -> list[Page]:
    pages: list[Page] = []
    for page_number in range(1, book.page_count + 1):
        page = session.exec(
            select(Page).where(Page.book_id == book.id, Page.page_number == page_number)
        ).first()
        if page is None:
            payload = planned_page_payload(page_number)
            page = Page(book_id=book.id or 0, page_number=page_number)
            page.page_type = str(payload["page_type"])
            page.scene_title = str(payload["scene_title"])
            page.story_text = str(payload["story_text"])
            page.illustration_direction = str(payload["illustration_direction"])
            page.characters_json = json.dumps(payload["characters"])
            page.environment = str(payload["environment"])
            page.emotion = str(payload["emotion"])
            page.camera = str(payload["camera"])
            page.hidden_objects_json = json.dumps(payload["hidden_objects"])
            page.text_safe_area = str(payload["text_safe_area"])
            page.status = "planned"
            session.add(page)
        pages.append(page)
    session.commit()
    for page in pages:
        session.refresh(page)
        page_path = PROJECT_ROOT / "books" / book.slug / "pages" / f"page_{page.page_number:03d}.yaml"
        if not page_path.exists():
            write_page_yaml(book, page)
    return pages


def write_page_yaml(book: Book, page: Page) -> Path:
    root = PROJECT_ROOT / "books" / book.slug / "pages"
    root.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
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
        "status": page.status,
    }
    path = root / f"page_{page.page_number:03d}.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def update_book_metadata(
    session: Session,
    book_slug: str,
    *,
    title: str,
    series: str,
    target_age: str,
    lesson: str,
    status: str,
) -> Book:
    book = get_book_by_slug(session, book_slug)
    if book is None:
        raise ValueError(f"Book not found: {book_slug}")
    book.title = title.strip() or book.title
    book.series = series.strip()
    book.target_age = target_age.strip()
    book.lesson = lesson.strip()
    book.status = status.strip() or book.status
    book.updated_at = utc_now()
    session.add(book)
    session.commit()
    session.refresh(book)
    write_book_yaml(book)
    return book


def update_book_page(
    session: Session,
    book_slug: str,
    page_number: int,
    *,
    scene_title: str,
    story_text: str,
    illustration_direction: str,
    status: str,
) -> Page:
    book = get_book_by_slug(session, book_slug)
    if book is None or book.id is None:
        raise ValueError(f"Book not found: {book_slug}")
    page = session.exec(
        select(Page).where(Page.book_id == book.id, Page.page_number == page_number)
    ).first()
    if page is None:
        page = Page(book_id=book.id, page_number=page_number)
    page.scene_title = scene_title.strip()
    page.story_text = story_text.strip()
    page.illustration_direction = illustration_direction.strip()
    page.status = status.strip() or page.status
    session.add(page)
    session.commit()
    session.refresh(page)
    write_page_yaml(book, page)
    return page


def generate_book_from_brief(
    session: Session,
    book_slug: str,
    *,
    idea: str,
    characters: str = "",
    objects: str = "",
    character_count: int = 3,
    object_count: int = 4,
    reference_notes: str = "",
) -> list[Page]:
    book = get_book_by_slug(session, book_slug)
    if book is None or book.id is None:
        raise ValueError(f"Book not found: {book_slug}")

    clean = clean_idea(idea, book)
    focus_characters = split_focus_list(characters, focus_character_defaults(book), character_count)
    if should_include_hackster_niko(book, characters) and "Hackster Niko" not in focus_characters:
        focus_characters.insert(0, "Hackster Niko")
    focus_items = split_focus_list(objects, HIDDEN_OBJECTS, object_count)

    if not book.lesson:
        book.lesson = f"Creative problem solving and responsible technology through: {idea_phrase(clean)}."
    book.status = "book plan generated"
    book.updated_at = utc_now()
    session.add(book)
    session.commit()
    session.refresh(book)

    ensure_book_files(session, book)
    write_planning_brief(
        book,
        idea=clean,
        focus_characters=focus_characters,
        focus_items=focus_items,
        reference_notes=reference_notes.strip(),
    )

    pages: list[Page] = []
    for page_number in range(1, book.page_count + 1):
        payload = generated_page_payload(
            book,
            page_number,
            idea=clean,
            focus_characters=focus_characters,
            focus_items=focus_items,
            reference_notes=reference_notes,
        )
        page = session.exec(
            select(Page).where(Page.book_id == book.id, Page.page_number == page_number)
        ).first()
        if page is None:
            page = Page(book_id=book.id, page_number=page_number)
        page.page_type = str(payload["page_type"])
        page.scene_title = str(payload["scene_title"])
        page.story_text = str(payload["story_text"])
        page.illustration_direction = str(payload["illustration_direction"])
        page.characters_json = json.dumps(payload["characters"])
        page.environment = str(payload["environment"])
        page.emotion = str(payload["emotion"])
        page.camera = str(payload["camera"])
        page.hidden_objects_json = json.dumps(payload["hidden_objects"])
        page.text_safe_area = str(payload["text_safe_area"])
        page.status = str(payload["status"])
        session.add(page)
        pages.append(page)

    session.commit()
    for page in pages:
        session.refresh(page)
        write_page_yaml(book, page)
    write_book_yaml(book)
    return pages


def generate_book_from_openai_brief(
    session: Session,
    book_slug: str,
    *,
    idea: str,
    characters: str = "",
    objects: str = "",
    character_count: int = 3,
    object_count: int = 4,
    reference_notes: str = "",
) -> list[Page]:
    from .ai_planner import plan_book_with_openai

    book = get_book_by_slug(session, book_slug)
    if book is None or book.id is None:
        raise ValueError(f"Book not found: {book_slug}")

    clean = clean_idea(idea, book)
    focus_characters = split_focus_list(characters, focus_character_defaults(book), character_count)
    if should_include_hackster_niko(book, characters) and "Hackster Niko" not in focus_characters:
        focus_characters.insert(0, "Hackster Niko")
    focus_items = split_focus_list(objects, HIDDEN_OBJECTS, object_count)
    plan = plan_book_with_openai(
        title=book.title,
        idea=clean,
        lesson=book.lesson,
        page_count=book.page_count,
        target_age=book.target_age,
        characters=focus_characters,
        objects=focus_items,
        reference_notes=reference_notes,
    )
    return apply_openai_plan_to_book(session, book, plan, idea=clean)


def generate_book_from_dgx_brief(
    session: Session,
    book_slug: str,
    *,
    idea: str,
    characters: str = "",
    objects: str = "",
    character_count: int = 3,
    object_count: int = 4,
    reference_notes: str = "",
    progress: Callable[[str, dict[str, Any]], None] | None = None,
) -> list[Page]:
    from ..automation.dgx_services import prepare_dgx_planner, release_dgx_planner_for_images
    from .ai_planner import plan_book_with_dgx

    book = get_book_by_slug(session, book_slug)
    if book is None or book.id is None:
        raise ValueError(f"Book not found: {book_slug}")

    clean = clean_idea(idea, book)
    focus_characters = split_focus_list(characters, focus_character_defaults(book), character_count)
    if should_include_hackster_niko(book, characters) and "Hackster Niko" not in focus_characters:
        focus_characters.insert(0, "Hackster Niko")
    focus_items = split_focus_list(objects, HIDDEN_OBJECTS, object_count)
    book.status = "DGX planning in progress"
    book.updated_at = utc_now()
    session.add(book)
    session.commit()
    session.refresh(book)
    ensure_book_files(session, book)
    write_planning_brief(
        book,
        idea=clean,
        focus_characters=focus_characters,
        focus_items=focus_items,
        reference_notes=reference_notes.strip(),
    )

    saved_page_numbers: set[int] = set()

    def save_planned_page(page_payload: dict[str, Any]) -> None:
        page_number = int(page_payload["page_number"])
        page = session.exec(
            select(Page).where(Page.book_id == book.id, Page.page_number == page_number)
        ).first()
        if page is None:
            page = Page(book_id=book.id, page_number=page_number)
        page.page_type = str(page_payload["page_type"])
        page.scene_title = str(page_payload["scene_title"])
        page.story_text = str(page_payload["story_text"])
        page.illustration_direction = str(page_payload["illustration_direction"])
        page.characters_json = json.dumps(page_payload["characters"])
        page.environment = str(page_payload["environment"])
        page.emotion = str(page_payload["emotion"])
        page.camera = str(page_payload["camera"])
        page.hidden_objects_json = json.dumps(page_payload["hidden_objects"])
        page.text_safe_area = str(page_payload["text_safe_area"])
        page.status = "AI planned"
        session.add(page)
        session.commit()
        session.refresh(page)
        write_page_yaml(book, page)
        saved_page_numbers.add(page_number)
        if progress:
            progress(
                "planner_page_saved",
                {
                    "message": f"DGX page {page_number} saved.",
                    "book_slug": book.slug,
                    "page_number": page_number,
                    "pages_saved": len(saved_page_numbers),
                    "pages_total": book.page_count,
                    "response_summary": _page_summary(page_payload),
                },
            )

    if progress:
        progress("dgx_starting", {"message": "Starting DGX planner service.", "book_slug": book.slug})
    prepare_dgx_planner()
    try:
        if progress:
            progress(
                "planner_request_submitted",
                {
                    "message": "Submitting story/layout request to DGX.",
                    "book_slug": book.slug,
                    "request_summary": planner_request_summary(
                        book,
                        idea=clean,
                        focus_characters=focus_characters,
                        focus_items=focus_items,
                        reference_notes=reference_notes,
                    ),
                },
            )
        plan = plan_book_with_dgx(
            title=book.title,
            idea=clean,
            lesson=book.lesson,
            page_count=book.page_count,
            target_age=book.target_age,
            characters=focus_characters,
            objects=focus_items,
            reference_notes=reference_notes,
            page_callback=save_planned_page,
        )
        if progress:
            progress(
                "planner_response_received",
                {
                    "message": "DGX returned a structured book plan.",
                    "book_slug": book.slug,
                    "title": str(plan.get("title") or book.title),
                    "pages": len(plan.get("pages") or []),
                    "response_summary": planner_response_summary(plan),
                },
            )
    finally:
        if progress:
            progress("dgx_releasing", {"message": "Releasing DGX planner memory for image generation.", "book_slug": book.slug})
        release_dgx_planner_for_images()
    pages = apply_openai_plan_to_book(session, book, plan, idea=clean)
    if progress:
        progress("pages_created", {"message": "Book pages were written from the DGX response.", "book_slug": book.slug, "pages": len(pages)})
    return pages


def planner_request_summary(
    book: Book,
    *,
    idea: str,
    focus_characters: list[str],
    focus_items: list[str],
    reference_notes: str,
) -> dict[str, Any]:
    return {
        "title": book.title,
        "page_count": book.page_count,
        "target_age": book.target_age,
        "lesson": short_text(book.lesson, 120),
        "idea": short_text(idea, 220),
        "focus_characters": focus_characters[:10],
        "focus_items": focus_items[:10],
        "reference_notes": short_text(reference_notes, 180),
        "requested_output": "Structured JSON book plan: title, lesson, summary, focus lists, and per-page story/layout fields.",
    }


def planner_response_summary(plan: dict[str, Any]) -> dict[str, Any]:
    pages = plan.get("pages") if isinstance(plan.get("pages"), list) else []
    page_samples: list[dict[str, Any]] = []
    for page in pages[:3]:
        if not isinstance(page, dict):
            continue
        page_samples.append(_page_summary(page))
    if len(pages) > 3 and isinstance(pages[-1], dict):
        page_samples.append(_page_summary(pages[-1]))
    return {
        "title": short_text(plan.get("title"), 120),
        "lesson": short_text(plan.get("lesson"), 120),
        "summary": short_text(plan.get("summary"), 240),
        "page_count": len(pages),
        "focus_characters": [str(item) for item in (plan.get("focus_characters") or [])][:10],
        "focus_items": [str(item) for item in (plan.get("focus_items") or [])][:10],
        "page_samples": page_samples,
    }


def _page_summary(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "page": page.get("page_number"),
        "type": short_text(page.get("page_type"), 40),
        "scene": short_text(page.get("scene_title"), 80),
        "story": short_text(page.get("story_text"), 120),
    }


def apply_openai_plan_to_book(
    session: Session,
    book: Book,
    plan: dict[str, Any],
    *,
    idea: str,
) -> list[Page]:
    if book.id is None:
        raise ValueError(f"Book not saved: {book.slug}")

    ai_lesson = str(plan.get("lesson") or "").strip()
    if ai_lesson:
        book.lesson = ai_lesson
    book.status = "AI book plan generated"
    book.updated_at = utc_now()
    session.add(book)
    session.commit()
    session.refresh(book)

    focus_characters = plan.get("focus_characters") or DEFAULT_FOCUS_CHARACTERS
    focus_items = plan.get("focus_items") or HIDDEN_OBJECTS
    write_planning_brief(
        book,
        idea=idea,
        focus_characters=list(focus_characters),
        focus_items=list(focus_items),
        reference_notes=str(plan.get("reference_notes") or ""),
    )

    pages: list[Page] = []
    for page_payload in plan["pages"]:
        page_number = int(page_payload["page_number"])
        page = session.exec(
            select(Page).where(Page.book_id == book.id, Page.page_number == page_number)
        ).first()
        if page is None:
            page = Page(book_id=book.id, page_number=page_number)
        page.page_type = str(page_payload["page_type"])
        page.scene_title = str(page_payload["scene_title"])
        page.story_text = str(page_payload["story_text"])
        page.illustration_direction = str(page_payload["illustration_direction"])
        page.characters_json = json.dumps(page_payload["characters"])
        page.environment = str(page_payload["environment"])
        page.emotion = str(page_payload["emotion"])
        page.camera = str(page_payload["camera"])
        page.hidden_objects_json = json.dumps(page_payload["hidden_objects"])
        page.text_safe_area = str(page_payload["text_safe_area"])
        page.status = "AI planned"
        session.add(page)
        pages.append(page)

    session.commit()
    for page in pages:
        session.refresh(page)
        write_page_yaml(book, page)
    write_book_yaml(book)
    return pages


def upsert_project(session: Session) -> Project:
    project = session.exec(select(Project).where(Project.name == "Hackster Niko Universe")).first()
    if project is None:
        project = Project(name="Hackster Niko Universe")

    project.description = "Reusable children’s book publishing platform for the Hackster Niko series."
    project.status = "active development"
    project.updated_at = utc_now()
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def upsert_password_dragon_book(session: Session) -> Book:
    book = get_book_by_slug(session, "book01_password_dragon")
    if book is None:
        book = Book(title="Hackster Niko and the Password Dragon", slug="book01_password_dragon")

    book.series = "Hackster Niko"
    book.target_age = "5-8"
    book.lesson = "Strong passwords and keeping secrets safe."
    book.page_count = 32
    book.trim_size = "8.5x8.5"
    book.status = "planned"
    book.updated_at = utc_now()
    session.add(book)
    session.commit()
    session.refresh(book)
    return book


def _story_page(page_number: int, beat: str, beat_index: int) -> dict[str, str | list[str]]:
    camera_cycle = ["wide establishing shot", "medium storybook view", "close warm character moment"]
    emotion_cycle = ["curious", "surprised", "caring", "confident", "playful", "relieved"]
    return {
        "page_type": "story",
        "scene_title": f"Story Beat {beat_index + 1}: {beat}",
        "story_text": f"Draft story text for page {page_number}: {beat}",
        "illustration_direction": (
            f"Show {beat.lower()} Keep the Cyber Forest friendly, bright, rounded, and readable."
        ),
        "characters": ["Hackster Niko"] if "forest celebrates" not in beat.lower() else ["Hackster Niko", "Cyber Forest friends"],
        "environment": "Cyber Forest",
        "emotion": emotion_cycle[beat_index % len(emotion_cycle)],
        "camera": camera_cycle[beat_index % len(camera_cycle)],
        "hidden_objects": HIDDEN_OBJECTS,
        "text_safe_area": "Leave clean open space for story text inside the 0.5 inch safe margin.",
        "status": "planned",
    }


def planned_page_payload(page_number: int) -> dict[str, str | list[str]]:
    if page_number == 1:
        return {
            "page_type": "front_matter",
            "scene_title": "Title Page",
            "story_text": "Hackster Niko and the Password Dragon",
            "illustration_direction": "Friendly title-page composition with Niko entering Cyber Forest.",
            "characters": ["Hackster Niko"],
            "environment": "Cyber Forest",
            "emotion": "wonder",
            "camera": "hero title-page view",
            "hidden_objects": [],
            "text_safe_area": "Large clean center/top area for editable title text.",
            "status": "planned",
        }
    if page_number == 2:
        return {
            "page_type": "front_matter",
            "scene_title": "Copyright",
            "story_text": "Copyright and publishing details.",
            "illustration_direction": "Simple soft pattern or small Niko icon area, no required full scene.",
            "characters": [],
            "environment": "",
            "emotion": "calm",
            "camera": "minimal layout",
            "hidden_objects": [],
            "text_safe_area": "Keep most of page open for editable copyright text.",
            "status": "planned",
        }
    if page_number == 3:
        return {
            "page_type": "front_matter",
            "scene_title": "Dedication",
            "story_text": "Dedication text placeholder.",
            "illustration_direction": "Gentle small illustration moment with Niko holding a glowing gear.",
            "characters": ["Hackster Niko"],
            "environment": "",
            "emotion": "kind",
            "camera": "quiet vignette",
            "hidden_objects": ["Golden Gear"],
            "text_safe_area": "Leave clean open center area for dedication text.",
            "status": "planned",
        }
    if 4 <= page_number <= 29:
        story_index = page_number - 4
        beat_index = min(int(story_index / 26 * len(STORY_BEATS)), len(STORY_BEATS) - 1)
        return _story_page(page_number, STORY_BEATS[beat_index], beat_index)
    if page_number == 30:
        return {
            "page_type": "ending",
            "scene_title": "The End",
            "story_text": "Every problem has a clever fix!",
            "illustration_direction": "Warm celebratory ending with Niko and friends in Cyber Forest.",
            "characters": ["Hackster Niko", "Password Dragon", "Cyber Forest friends"],
            "environment": "Cyber Forest",
            "emotion": "celebration",
            "camera": "wide joyful finale",
            "hidden_objects": HIDDEN_OBJECTS,
            "text_safe_area": "Leave open space for The End and catchphrase as editable text.",
            "status": "planned",
        }
    if page_number == 31:
        return {
            "page_type": "activity",
            "scene_title": "Password Challenge",
            "story_text": "Activity page: build a silly strong password with a trusted grown-up.",
            "illustration_direction": "Activity layout with Niko pointing to blank editable worksheet areas.",
            "characters": ["Hackster Niko"],
            "environment": "",
            "emotion": "encouraging",
            "camera": "activity page layout",
            "hidden_objects": ["Golden Gear", "Blue Crystal"],
            "text_safe_area": "Leave large editable worksheet zones.",
            "status": "planned",
        }
    return {
        "page_type": "teaser",
        "scene_title": "Book 2 Teaser: Sneaky Phish",
        "story_text": "A suspicious email teaser hints at Book 2: Sneaky Phish.",
        "illustration_direction": "Niko notices a friendly, non-scary suspicious email clue on a glowing tablet.",
        "characters": ["Hackster Niko"],
        "environment": "Hackster HQ",
        "emotion": "curious",
        "camera": "teaser close-up",
        "hidden_objects": ["Tiny Bug", "Mini Robot"],
        "text_safe_area": "Leave clean open area for teaser copy.",
        "status": "planned",
    }


def plan_book(session: Session, book_slug: str) -> list[Page]:
    book = get_book_by_slug(session, book_slug)
    if book is None:
        raise ValueError(f"Book not found: {book_slug}. Run seed first.")

    pages: list[Page] = []
    for page_number in range(1, book.page_count + 1):
        payload = planned_page_payload(page_number)
        page = session.exec(
            select(Page).where(Page.book_id == book.id, Page.page_number == page_number)
        ).first()
        if page is None:
            page = Page(book_id=book.id, page_number=page_number)

        page.page_type = str(payload["page_type"])
        page.scene_title = str(payload["scene_title"])
        page.story_text = str(payload["story_text"])
        page.illustration_direction = str(payload["illustration_direction"])
        page.characters_json = json.dumps(payload["characters"])
        page.environment = str(payload["environment"])
        page.emotion = str(payload["emotion"])
        page.camera = str(payload["camera"])
        page.hidden_objects_json = json.dumps(payload["hidden_objects"])
        page.text_safe_area = str(payload["text_safe_area"])
        page.status = str(payload["status"])
        session.add(page)
        pages.append(page)

    book.status = "page plan generated"
    book.updated_at = utc_now()
    session.add(book)
    session.commit()
    for page in pages:
        session.refresh(page)
        write_page_yaml(book, page)
    write_book_yaml(book)
    return pages
