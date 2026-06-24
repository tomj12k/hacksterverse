"""Database models for projects, books, pages, prompts, and production reports."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Project(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: str = ""
    status: str = "planning"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Character(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    slug: str = Field(index=True, unique=True)
    role: str = ""
    description: str = ""
    appearance: str = ""
    personality: str = ""
    colors_json: str = "{}"
    style_notes: str = ""
    reference_image_path: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Environment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    slug: str = Field(index=True, unique=True)
    description: str = ""
    visual_language: str = ""
    palette_json: str = "{}"
    reference_image_path: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Gadget(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    slug: str = Field(index=True, unique=True)
    description: str = ""
    design_notes: str = ""
    safety_notes: str = ""
    reference_image_path: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Book(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    slug: str = Field(index=True, unique=True)
    series: str = ""
    target_age: str = ""
    lesson: str = ""
    page_count: int = 32
    trim_size: str = "8.5x8.5"
    status: str = "planning"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Page(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    book_id: int = Field(index=True, foreign_key="book.id")
    page_number: int = Field(index=True)
    page_type: str = "story"
    scene_title: str = ""
    story_text: str = ""
    illustration_direction: str = ""
    characters_json: str = "[]"
    environment: str = ""
    emotion: str = ""
    camera: str = ""
    hidden_objects_json: str = "[]"
    text_safe_area: str = ""
    illustration_path: str = ""
    prompt_path: str = ""
    status: str = "planned"


class Prompt(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    prompt_type: str = Field(index=True)
    related_type: str = Field(index=True)
    related_id: int = Field(index=True)
    title: str = ""
    prompt_text: str = ""
    output_path: str = ""
    status: str = "generated"
    created_at: datetime = Field(default_factory=utc_now)


class PrintReport(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    file_path: str = ""
    width_px: int = 0
    height_px: int = 0
    dpi_x: float = 0
    dpi_y: float = 0
    required_width_px: int = 2625
    required_height_px: int = 2625
    pass_fail: bool = False
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class GenerationJob(SQLModel, table=True):
    """Durable record of a book-generation job so its state survives restart.

    The authoritative live state is the in-memory store; this table is a
    write-through mirror used for status reads after a restart and for
    crash-recovery (orphaned queued/running rows are marked failed on startup).
    ``events`` and ``result`` are JSON-encoded.
    """

    job_id: str = Field(primary_key=True)
    book_slug: str = Field(default="", index=True)
    redirect_url: str = ""
    status: str = Field(default="queued", index=True)
    stage: str = "queued"
    progress: int = 0
    error: str = ""
    events_json: str = "[]"
    result_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

