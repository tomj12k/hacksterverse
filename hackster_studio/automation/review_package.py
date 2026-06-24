"""Create human review files for each generated page."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .quality_checks import ImageValidationResult, page_review_checklist


def write_review_files(
    *,
    pages: list[dict[str, Any]],
    validations: dict[int, ImageValidationResult],
    review_dir: Path,
    force: bool = False,
) -> list[Path]:
    review_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    checklist = page_review_checklist()

    for page in pages:
        page_number = int(page["page_number"])
        validation = validations.get(page_number)
        output_path = review_dir / f"page_{page_number:03d}_review.md"
        if output_path.exists() and not force:
            paths.append(output_path)
            continue

        checklist_lines = "\n".join(f"- [ ] {item}" for item in checklist)
        validation_notes = "\n".join(f"- {note}" for note in (validation.notes if validation else ["Not validated."]))
        text = f"""# Page {page_number:03d} Review

Approval status: {page.get("approval_status", "needs_review")}

## Scene

{page.get("scene_title", "")}

## Story Text

{page.get("story_text", "")}

## Prompt

Prompt path: `{page.get("prompt_path", "")}`

```text
{Path(page.get("prompt_path", "")).read_text(encoding="utf-8") if Path(page.get("prompt_path", "")).exists() else "Prompt file missing."}
```

## Image

Image path: `{page.get("illustration_path", "")}`

## Checklist

{checklist_lines}

## Image Validation

{validation_notes}

## Reviewer Notes

- TODO: Add human review notes.
- TODO: Mark approval_status as approved only after visual QA.
"""
        output_path.write_text(text, encoding="utf-8")
        paths.append(output_path)

    return paths

