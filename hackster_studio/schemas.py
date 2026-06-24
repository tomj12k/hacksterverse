"""Small typed structures shared by services and routes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GeneratedPrompt:
    title: str
    prompt_text: str
    output_path: Path


@dataclass(frozen=True)
class CountSummary:
    projects: int
    characters: int
    environments: int
    gadgets: int
    books: int
    pages: int
    prompts: int
    print_reports: int

