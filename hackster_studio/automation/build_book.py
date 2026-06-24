"""Public entry points for one-command book builds."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from .pipeline import BuildOptions, BookBuildPipeline, BuildResult


def build_book(book_yaml: Path, options: BuildOptions, console: Console | None = None) -> BuildResult:
    """Run the complete local book build pipeline."""
    pipeline = BookBuildPipeline(book_yaml=book_yaml, options=options, console=console)
    return pipeline.run()

