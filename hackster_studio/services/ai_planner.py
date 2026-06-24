"""AI-backed book planning helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from dotenv import load_dotenv
from openai import OpenAI

from ..config import PROJECT_ROOT


ENV_FILE = PROJECT_ROOT / ".env"


def _validated_base_url(url: str) -> str:
    """Normalize and validate a user-supplied LLM base URL.

    The value is later passed to ``OpenAI(base_url=...)``, so it must be a
    real http(s) endpoint — reject other schemes (file://, gopher://, etc.)
    and empty hosts to reduce the SSRF surface.

    :raises ValueError: if the URL is not a valid http/https URL with a host.
    :rtype: str
    """
    cleaned = url.strip().rstrip("/")
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("DGX base URL must be an http(s) URL with a host.")
    return cleaned
DEFAULT_OPENAI_TEXT_MODEL = "gpt-5.5"
DEFAULT_DGX_LLM_BASE_URL = "http://192.168.68.136:8000/v1"
DEFAULT_DGX_TEXT_MODEL = "Qwen3-32B-AWQ"


class AIPlannerUnavailable(RuntimeError):
    """Raised when OpenAI planning is requested but not configured."""


def openai_settings() -> dict[str, Any]:
    load_dotenv(ENV_FILE, override=False)
    api_key = os.getenv("OPENAI_API_KEY", "")
    dgx_base_url = os.getenv("DGX_LLM_BASE_URL") or DEFAULT_DGX_LLM_BASE_URL
    return {
        "api_key_configured": bool(api_key.strip()),
        "text_model": os.getenv("OPENAI_TEXT_MODEL") or DEFAULT_OPENAI_TEXT_MODEL,
        "image_model": os.getenv("OPENAI_IMAGE_MODEL") or "gpt-image-1",
        "dgx_configured": bool(dgx_base_url.strip()),
        "dgx_base_url": dgx_base_url,
        "dgx_text_model": os.getenv("DGX_LLM_MODEL") or DEFAULT_DGX_TEXT_MODEL,
        "env_file": ENV_FILE,
    }


def write_openai_settings(
    *,
    api_key: str = "",
    text_model: str = "",
    image_model: str = "",
    dgx_base_url: str = "",
    dgx_api_key: str = "",
    dgx_text_model: str = "",
) -> Path:
    values = _read_env_file(ENV_FILE)
    if api_key.strip():
        values["OPENAI_API_KEY"] = api_key.strip()
    if text_model.strip():
        values["OPENAI_TEXT_MODEL"] = text_model.strip()
    if image_model.strip():
        values["OPENAI_IMAGE_MODEL"] = image_model.strip()
    if dgx_base_url.strip():
        values["DGX_LLM_BASE_URL"] = _validated_base_url(dgx_base_url)
    if dgx_api_key.strip():
        values["DGX_LLM_API_KEY"] = dgx_api_key.strip()
    if dgx_text_model.strip():
        values["DGX_LLM_MODEL"] = dgx_text_model.strip()
    values.setdefault("OPENAI_TEXT_MODEL", DEFAULT_OPENAI_TEXT_MODEL)
    values.setdefault("OPENAI_IMAGE_MODEL", "gpt-image-1")
    values.setdefault("DGX_LLM_BASE_URL", DEFAULT_DGX_LLM_BASE_URL)
    values.setdefault("DGX_LLM_MODEL", DEFAULT_DGX_TEXT_MODEL)
    _write_env_file(ENV_FILE, values)
    load_dotenv(ENV_FILE, override=True)
    return ENV_FILE


def plan_book_with_openai(
    *,
    title: str,
    idea: str,
    lesson: str,
    page_count: int,
    target_age: str,
    characters: list[str],
    objects: list[str],
    reference_notes: str,
    client: OpenAI | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    load_dotenv(ENV_FILE, override=False)
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if client is None and not api_key:
        raise AIPlannerUnavailable(
            "OpenAI is not configured. Add OPENAI_API_KEY on the AI Setup page or in .env."
        )

    active_client = client or OpenAI(api_key=api_key)
    active_model = model or os.getenv("OPENAI_TEXT_MODEL") or DEFAULT_OPENAI_TEXT_MODEL
    requested_pages = max(1, min(96, int(page_count or 32)))
    prompt = _planner_prompt(
        title=title,
        idea=idea,
        lesson=lesson,
        page_count=requested_pages,
        target_age=target_age,
        characters=characters,
        objects=objects,
        reference_notes=reference_notes,
    )

    try:
        response = active_client.responses.create(
            model=active_model,
            input=prompt,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "hackster_book_plan",
                    "schema": _book_plan_schema(requested_pages),
                    "strict": True,
                }
            },
        )
    except TypeError:
        response = active_client.responses.create(model=active_model, input=prompt)

    plan = _parse_response_json(getattr(response, "output_text", ""))
    return validate_ai_plan(plan, requested_pages)


def plan_book_with_dgx(
    *,
    title: str,
    idea: str,
    lesson: str,
    page_count: int,
    target_age: str,
    characters: list[str],
    objects: list[str],
    reference_notes: str,
    client: OpenAI | None = None,
    model: str | None = None,
    page_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    load_dotenv(ENV_FILE, override=False)
    base_url = (os.getenv("DGX_LLM_BASE_URL") or DEFAULT_DGX_LLM_BASE_URL).strip().rstrip("/")
    if not base_url:
        raise AIPlannerUnavailable(
            "DGX planner is not configured. Add DGX_LLM_BASE_URL on the AI Setup page or in .env."
        )

    active_client = client or OpenAI(
        api_key=os.getenv("DGX_LLM_API_KEY") or "local-dgx",
        base_url=base_url,
    )
    active_model = model or os.getenv("DGX_LLM_MODEL") or DEFAULT_DGX_TEXT_MODEL
    requested_pages = max(1, min(96, int(page_count or 32)))
    direct_page_limit = max(1, int(os.getenv("DGX_LLM_DIRECT_PAGE_LIMIT", "8")))
    if requested_pages > direct_page_limit and os.getenv("DGX_LLM_PAGE_BY_PAGE", "1") != "0":
        return _plan_book_with_dgx_pages(
            active_client,
            model=active_model,
            title=title,
            idea=idea,
            lesson=lesson,
            page_count=requested_pages,
            target_age=target_age,
            characters=characters,
            objects=objects,
            reference_notes=reference_notes,
            page_callback=page_callback,
        )

    prompt = _planner_prompt(
        title=title,
        idea=idea,
        lesson=lesson,
        page_count=requested_pages,
        target_age=target_age,
        characters=characters,
        objects=objects,
        reference_notes=reference_notes,
    )
    plan = _call_openai_compatible_json(
        active_client,
        model=active_model,
        prompt=prompt,
        page_count=requested_pages,
    )
    try:
        return validate_ai_plan(plan, requested_pages)
    except ValueError as exc:
        if requested_pages > 1 and os.getenv("DGX_LLM_PAGE_BY_PAGE_FALLBACK", "1") != "0":
            try:
                return _plan_book_with_dgx_pages(
                    active_client,
                    model=active_model,
                    title=title,
                    idea=idea,
                    lesson=lesson,
                    page_count=requested_pages,
                    target_age=target_age,
                    characters=characters,
                    objects=objects,
                    reference_notes=reference_notes,
                    page_callback=page_callback,
                )
            except Exception as page_exc:
                message = _invalid_plan_message(exc, plan, requested_pages)
                raise ValueError(f"{message} Page-by-page fallback also failed: {page_exc}") from page_exc
        raise ValueError(_invalid_plan_message(exc, plan, requested_pages)) from exc


def regenerate_page_with_dgx(
    *,
    title: str,
    idea: str,
    lesson: str,
    page_count: int,
    page_number: int,
    target_age: str,
    characters: list[str],
    objects: list[str],
    reference_notes: str,
    page_context: dict[str, Any] | None = None,
    client: OpenAI | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    load_dotenv(ENV_FILE, override=False)
    base_url = (os.getenv("DGX_LLM_BASE_URL") or DEFAULT_DGX_LLM_BASE_URL).strip().rstrip("/")
    if not base_url:
        raise AIPlannerUnavailable(
            "DGX planner is not configured. Add DGX_LLM_BASE_URL on the AI Setup page or in .env."
        )

    active_client = client or OpenAI(
        api_key=os.getenv("DGX_LLM_API_KEY") or "local-dgx",
        base_url=base_url,
    )
    active_model = model or os.getenv("DGX_LLM_MODEL") or DEFAULT_DGX_TEXT_MODEL
    requested_pages = max(1, min(96, int(page_count or 32)))
    target_page = max(1, min(requested_pages, int(page_number or 1)))
    response = _chat_json(
        active_client,
        model=active_model,
        prompt=_planner_page_regeneration_prompt(
            title=title,
            idea=idea,
            lesson=lesson,
            page_count=requested_pages,
            page_number=target_page,
            target_age=target_age,
            characters=characters,
            objects=objects,
            reference_notes=reference_notes,
            page_context=page_context or {},
        ),
        schema=_book_single_page_schema(target_page),
        max_tokens=int(os.getenv("DGX_LLM_PAGE_MAX_TOKENS", "2048")),
    )
    return _normalize_plan_page(response.get("page"), target_page)


def validate_ai_plan(plan: dict[str, Any], page_count: int) -> dict[str, Any]:
    pages = plan.get("pages")
    if not isinstance(pages, list) or len(pages) != page_count:
        raise ValueError(f"OpenAI planner returned {len(pages) if isinstance(pages, list) else 0} pages; expected {page_count}.")

    normalized_pages: list[dict[str, Any]] = []
    for index, page in enumerate(pages, start=1):
        normalized_pages.append(_normalize_plan_page(page, index))

    return {
        "title": str(plan.get("title") or ""),
        "lesson": str(plan.get("lesson") or ""),
        "summary": str(plan.get("summary") or ""),
        "focus_characters": _string_list(plan.get("focus_characters")),
        "focus_items": _string_list(plan.get("focus_items")),
        "reference_notes": str(plan.get("reference_notes") or ""),
        "pages": normalized_pages,
    }


def _normalize_plan_page(page: Any, page_number: int) -> dict[str, Any]:
    if not isinstance(page, dict):
        raise ValueError(f"OpenAI planner page {page_number} is not an object.")
    return {
        "page_number": page_number,
        "page_type": str(page.get("page_type") or "story"),
        "scene_title": str(page.get("scene_title") or f"Page {page_number}"),
        "story_text": str(page.get("story_text") or ""),
        "illustration_direction": str(page.get("illustration_direction") or ""),
        "characters": _string_list(page.get("characters")),
        "environment": str(page.get("environment") or ""),
        "emotion": str(page.get("emotion") or "curious"),
        "camera": str(page.get("camera") or "storybook view"),
        "hidden_objects": _string_list(page.get("hidden_objects")),
        "text_safe_area": str(page.get("text_safe_area") or "Leave editable text space inside safe margins."),
    }


def _plan_book_with_dgx_pages(
    client: OpenAI,
    *,
    model: str,
    title: str,
    idea: str,
    lesson: str,
    page_count: int,
    target_age: str,
    characters: list[str],
    objects: list[str],
    reference_notes: str,
    page_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    overview = _chat_json(
        client,
        model=model,
        prompt=_planner_overview_prompt(
            title=title,
            idea=idea,
            lesson=lesson,
            page_count=page_count,
            target_age=target_age,
            characters=characters,
            objects=objects,
            reference_notes=reference_notes,
        ),
        schema=_book_overview_schema(page_count),
        max_tokens=int(os.getenv("DGX_LLM_OVERVIEW_MAX_TOKENS", "4096")),
    )

    outline = overview.get("page_outline")
    if not isinstance(outline, list) or len(outline) != page_count:
        raise ValueError(
            f"DGX overview returned {len(outline) if isinstance(outline, list) else 0} outline pages; expected {page_count}."
        )

    pages: list[dict[str, Any]] = []
    for page_number in range(1, page_count + 1):
        page_response = _chat_json(
            client,
            model=model,
            prompt=_planner_single_page_prompt(
                overview=overview,
                page_number=page_number,
                page_count=page_count,
                title=title,
                idea=idea,
                lesson=lesson,
                target_age=target_age,
                characters=characters,
                objects=objects,
                reference_notes=reference_notes,
            ),
            schema=_book_single_page_schema(page_number),
            max_tokens=int(os.getenv("DGX_LLM_PAGE_MAX_TOKENS", "2048")),
        )
        normalized_page = _normalize_plan_page(page_response.get("page"), page_number)
        pages.append(normalized_page)
        if page_callback:
            page_callback(dict(normalized_page))

    return validate_ai_plan(
        {
            "title": overview.get("title") or title,
            "lesson": overview.get("lesson") or lesson,
            "summary": overview.get("summary") or "",
            "focus_characters": overview.get("focus_characters") or characters,
            "focus_items": overview.get("focus_items") or objects,
            "reference_notes": overview.get("reference_notes") or reference_notes,
            "pages": pages,
        },
        page_count,
    )


def _invalid_plan_message(exc: Exception, plan: dict[str, Any], requested_pages: int) -> str:
    pages = plan.get("pages")
    if isinstance(pages, list):
        pages_detail = f"{len(pages)} page objects"
    else:
        pages_detail = type(pages).__name__
    preview = json.dumps(_compact_plan_preview(plan), ensure_ascii=True)
    if len(preview) > 900:
        preview = preview[:897].rstrip() + "..."
    return (
        f"{exc} DGX returned invalid planner JSON for a {requested_pages}-page book. "
        f"Top-level keys: {sorted(str(key) for key in plan.keys())}. "
        f"pages field: {pages_detail}. Compact response preview: {preview}"
    )


def _compact_plan_preview(plan: dict[str, Any]) -> dict[str, Any]:
    preview: dict[str, Any] = {}
    for key in ("title", "lesson", "summary", "focus_characters", "focus_items", "pages", "error", "message"):
        if key not in plan:
            continue
        value = plan[key]
        if isinstance(value, str):
            preview[key] = value[:240]
        elif isinstance(value, list):
            preview[key] = value[:3]
        elif isinstance(value, dict):
            preview[key] = {str(item_key): str(item_value)[:160] for item_key, item_value in list(value.items())[:6]}
        else:
            preview[key] = value
    return preview


def _planner_prompt(
    *,
    title: str,
    idea: str,
    lesson: str,
    page_count: int,
    target_age: str,
    characters: list[str],
    objects: list[str],
    reference_notes: str,
) -> str:
    uses_hackster_niko = "hackster niko" in f"{title} {' '.join(characters)}".lower()
    planner_identity = (
        "You are the senior children's book planner for the Hackster Niko franchise."
        if uses_hackster_niko
        else "You are a senior children's book planner for an original children's publishing studio."
    )
    franchise_rules = (
        """
Franchise rules:
- Hackster Niko is a small friendly learning robot, model HN-01, age equivalent 7, he/him, Junior Hackster.
- Mission: inspire kids to solve problems with kindness, curiosity, creativity, teamwork, and responsible technology.
- Catchphrase: Every problem has a clever fix!
- Art direction: bright premium children's picture book, dimensional but friendly, no weapons, no scary imagery.
- Important production rule: do not bake readable story text into illustration prompts. Text stays editable.
- Niko should be a separate posable character layer when possible, not painted into backgrounds unless the page is front matter or a tiny icon.
"""
        if uses_hackster_niko
        else """
Production rules:
- Build only around the requested title, characters, objects, and reference notes.
- Do not introduce Hackster Niko, robots, cyber-forest lore, password-dragon lore, or other Hackster franchise characters unless explicitly requested.
- Use friendly, age-appropriate scenes for the requested target age.
- Avoid weapons, gore, horror, or scary imagery.
- Keep recurring characters visually consistent across all pages.
- Important production rule: do not bake readable story text into illustration prompts. Text stays editable.
"""
    )
    default_title = "Untitled Hackster Niko Book" if uses_hackster_niko else "Untitled Picture Book"
    default_idea = (
        "Create a friendly Hackster Niko technology-safety adventure."
        if uses_hackster_niko
        else "Create a friendly original picture-book adventure."
    )
    default_characters = "Hackster Niko, Byte, one story friend" if uses_hackster_niko else "main character and supporting friends"
    return f"""
{planner_identity}

Create a complete {page_count}-page picture-book plan.

{franchise_rules}

Inputs:
- Working title: {title or default_title}
- Idea: {idea or default_idea}
- Lesson: {lesson or "Responsible technology and kind problem solving."}
- Target age: {target_age or "5-8"}
- Focus characters requested: {", ".join(characters) if characters else default_characters}
- Objects or hidden items requested: {", ".join(objects) if objects else "Golden Gear, Tiny Bug, Blue Crystal, Mini Robot"}
- Reference notes: {reference_notes or "No additional reference notes yet."}

	Return only JSON matching the schema. Story text should be polished dialogue/narration, not production notes.
	""".strip()


def _planner_overview_prompt(
    *,
    title: str,
    idea: str,
    lesson: str,
    page_count: int,
    target_age: str,
    characters: list[str],
    objects: list[str],
    reference_notes: str,
) -> str:
    return f"""
You are a senior children's book planner.

Create only the high-level plan for a {page_count}-page book. Do not write full page text yet.

Production rules:
- Keep story text separate from illustrations; readable text must remain editable later.
- Use friendly, age-appropriate scenes for ages {target_age or "5-8"}.
- Avoid weapons, gore, horror, or scary imagery.
- Keep recurring characters visually consistent across all pages.

Inputs:
- Working title: {title or "Untitled Book"}
- Idea: {idea or "Create a friendly picture-book adventure."}
- Lesson: {lesson or "Kind problem solving."}
- Focus characters requested: {", ".join(characters) if characters else "main character and supporting friends"}
- Objects or hidden items requested: {", ".join(objects) if objects else "recurring hidden objects"}
- Reference notes: {reference_notes or "No additional reference notes yet."}

Return only JSON matching the schema. Include exactly {page_count} page_outline entries.
""".strip()


def _planner_single_page_prompt(
    *,
    overview: dict[str, Any],
    page_number: int,
    page_count: int,
    title: str,
    idea: str,
    lesson: str,
    target_age: str,
    characters: list[str],
    objects: list[str],
    reference_notes: str,
) -> str:
    page_outline = overview.get("page_outline") if isinstance(overview.get("page_outline"), list) else []
    target_outline = {}
    for item in page_outline:
        if isinstance(item, dict) and int(item.get("page_number") or 0) == page_number:
            target_outline = item
            break
    return f"""
You are writing one production-ready page for a children's book.

Write page {page_number} of {page_count} only. Return exactly one page object.

Book overview:
{json.dumps(_compact_plan_preview(overview), ensure_ascii=True)}

Target page outline:
{json.dumps(target_outline, ensure_ascii=True)}

Inputs:
- Working title: {title or overview.get("title") or "Untitled Book"}
- Idea: {idea or "Create a friendly picture-book adventure."}
- Lesson: {lesson or overview.get("lesson") or "Kind problem solving."}
- Target age: {target_age or "5-8"}
- Focus characters: {", ".join(characters) if characters else ", ".join(_string_list(overview.get("focus_characters")))}
- Objects or hidden items: {", ".join(objects) if objects else ", ".join(_string_list(overview.get("focus_items")))}
- Reference notes: {reference_notes or overview.get("reference_notes") or "No additional reference notes yet."}

Rules:
- story_text must be final reader-facing narration/dialogue, not production annotations.
- illustration_direction must describe only the image; do not include readable text in the art.
- characters should list only characters visible or important on this page.
- hidden_objects should list small recurring objects to hide on this page when appropriate.
- text_safe_area should tell the layout where editable text can sit.

	Return only JSON matching the schema.
	""".strip()


def _planner_page_regeneration_prompt(
    *,
    title: str,
    idea: str,
    lesson: str,
    page_count: int,
    page_number: int,
    target_age: str,
    characters: list[str],
    objects: list[str],
    reference_notes: str,
    page_context: dict[str, Any],
) -> str:
    compact_context = {
        "current_page": page_context.get("current_page", {}),
        "previous_page": page_context.get("previous_page", {}),
        "next_page": page_context.get("next_page", {}),
    }
    return f"""
You are revising exactly one page of a children's book production plan.

Regenerate page {page_number} of {page_count} only. Keep continuity with nearby pages and improve the selected page.

Book inputs:
- Working title: {title or "Untitled Book"}
- Idea: {idea or "Create a friendly picture-book adventure."}
- Lesson: {lesson or "Kind problem solving."}
- Target age: {target_age or "5-8"}
- Focus characters: {", ".join(characters) if characters else "main character and supporting friends"}
- Objects or hidden items: {", ".join(objects) if objects else "recurring hidden objects"}
- Reference notes: {reference_notes or "No additional reference notes yet."}

Nearby page context:
{json.dumps(compact_context, ensure_ascii=True)}

Rules:
- Return only the replacement page object under the top-level "page" key.
- story_text must be final reader-facing narration/dialogue, not production notes.
- illustration_direction must describe the image only; do not include readable story text in the art.
- Preserve the requested characters and objects unless the selected page clearly should omit them.
- Keep the tone age-appropriate, visually clear, and production-ready.
""".strip()


def _book_plan_schema(page_count: int) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string"},
            "lesson": {"type": "string"},
            "summary": {"type": "string"},
            "focus_characters": {"type": "array", "items": {"type": "string"}},
            "focus_items": {"type": "array", "items": {"type": "string"}},
            "reference_notes": {"type": "string"},
            "pages": {"type": "array", "minItems": page_count, "maxItems": page_count, "items": _book_page_schema()},
        },
        "required": [
            "title",
            "lesson",
            "summary",
            "focus_characters",
            "focus_items",
            "reference_notes",
            "pages",
        ],
    }


def _book_page_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "page_type": {"type": "string"},
            "scene_title": {"type": "string"},
            "story_text": {"type": "string"},
            "illustration_direction": {"type": "string"},
            "characters": {"type": "array", "items": {"type": "string"}},
            "environment": {"type": "string"},
            "emotion": {"type": "string"},
            "camera": {"type": "string"},
            "hidden_objects": {"type": "array", "items": {"type": "string"}},
            "text_safe_area": {"type": "string"},
        },
        "required": [
            "page_type",
            "scene_title",
            "story_text",
            "illustration_direction",
            "characters",
            "environment",
            "emotion",
            "camera",
            "hidden_objects",
            "text_safe_area",
        ],
    }


def _book_overview_schema(page_count: int) -> dict[str, Any]:
    outline_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "page_number": {"type": "integer"},
            "page_type": {"type": "string"},
            "scene_title": {"type": "string"},
            "beat": {"type": "string"},
            "characters": {"type": "array", "items": {"type": "string"}},
            "environment": {"type": "string"},
        },
        "required": ["page_number", "page_type", "scene_title", "beat", "characters", "environment"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string"},
            "lesson": {"type": "string"},
            "summary": {"type": "string"},
            "focus_characters": {"type": "array", "items": {"type": "string"}},
            "focus_items": {"type": "array", "items": {"type": "string"}},
            "reference_notes": {"type": "string"},
            "page_outline": {"type": "array", "minItems": page_count, "maxItems": page_count, "items": outline_schema},
        },
        "required": [
            "title",
            "lesson",
            "summary",
            "focus_characters",
            "focus_items",
            "reference_notes",
            "page_outline",
        ],
    }


def _book_single_page_schema(page_number: int) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "page": _book_page_schema(),
        },
        "required": ["page"],
    }


def _parse_response_json(output_text: str) -> dict[str, Any]:
    text = output_text.strip()
    if "<think>" in text and "</think>" in text:
        text = text.split("</think>", 1)[1].strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("OpenAI planner did not return valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise ValueError("OpenAI planner JSON root must be an object.")
    return parsed


def _call_openai_compatible_json(
    client: OpenAI,
    *,
    model: str,
    prompt: str,
    page_count: int,
) -> dict[str, Any]:
    return _chat_json(
        client,
        model=model,
        prompt=prompt,
        schema=_book_plan_schema(page_count),
        max_tokens=int(os.getenv("DGX_LLM_MAX_TOKENS", "8192")),
    )


def _chat_json(
    client: OpenAI,
    *,
    model: str,
    prompt: str,
    schema: dict[str, Any],
    max_tokens: int,
) -> dict[str, Any]:
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Return only valid JSON. Do not wrap the JSON in Markdown. "
                    "Match the user's requested schema and page count exactly. "
                    "Do not include reasoning or analysis. /no_think"
                ),
            },
            {
                "role": "user",
                "content": "/no_think\n\n"
                + prompt
                + "\n\nJSON schema:\n"
                + json.dumps(schema, ensure_ascii=True),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=max(256, max_tokens),
    )
    content = completion.choices[0].message.content or ""
    return _parse_response_json(content)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _write_env_file(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Hackster Studio local secrets and AI settings.",
        "# This file is ignored by Git.",
    ]
    for key in sorted(values):
        # Strip CR/LF so a value can never inject extra .env lines (and thus
        # arbitrary env vars) when this file is re-read via load_dotenv().
        safe_value = str(values[key]).replace("\r", " ").replace("\n", " ")
        lines.append(f"{key}={safe_value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
