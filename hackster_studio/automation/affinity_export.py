"""Create a simple per-page handoff package for Affinity Publisher."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


def create_affinity_package(
    *,
    pages: list[dict[str, Any]],
    output_dir: Path,
    force: bool = False,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for page in pages:
        page_number = int(page["page_number"])
        page_dir = output_dir / f"page_{page_number:03d}"
        page_dir.mkdir(parents=True, exist_ok=True)

        files = {
            "page.yaml": yaml.safe_dump(page, sort_keys=False, allow_unicode=False),
            "story_text.txt": str(page.get("story_text", "")),
            "illustration_path.txt": str(page.get("illustration_path", "")),
            "layout.json": json.dumps(
                {
                    "page_number": page_number,
                    "trim_size": "8.5x8.5",
                    "bleed_inches": 0.125,
                    "safe_margin_inches": 0.5,
                    "text_safe_area": page.get("text_safe_area", ""),
                    "illustration_path": page.get("illustration_path", ""),
                    "prompt_path": page.get("prompt_path", ""),
                },
                indent=2,
            )
            + "\n",
        }

        for filename, content in files.items():
            path = page_dir / filename
            if path.exists() and not force:
                written.append(path)
                continue
            path.write_text(content, encoding="utf-8")
            written.append(path)

    return written

