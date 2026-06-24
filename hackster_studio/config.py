"""Project paths and small configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
ASSETS_DIR = PROJECT_ROOT / "assets"
GENERATED_DIR = DATA_DIR / "generated"
LAYERS_DIR = ASSETS_DIR / "layers"
GENERATED_PAGES_DIR = GENERATED_DIR / "pages"
DATABASE_PATH = Path(os.getenv("HACKSTER_STUDIO_DB", DATA_DIR / "hackster_studio.sqlite3"))

BOOKS_DIR = PROJECT_ROOT / "books"
SCENES_DIR = PROJECT_ROOT / "storybook_scenes"
MOVIES_DIR = PROJECT_ROOT / "movies"

def asset_serve_roots(project_root: Path = PROJECT_ROOT) -> tuple[Path, ...]:
    """Directories whose files may be served / opened from untrusted input.

    Derived from ``project_root`` so callers that relocate the root (e.g. tests)
    stay consistent. Deliberately excludes the project root itself, ``data/``
    (which holds the SQLite DB), ``.env``, ``configs/``, and the
    ``hackster_studio`` source tree.

    :rtype: tuple[Path, ...]
    """
    return (
        project_root / "assets",
        project_root / "data" / "generated",
        project_root / "books",
        project_root / "storybook_scenes",
        project_root / "movies",
    )


# Default (module-load) serve roots for non-relocated callers.
ASSET_SERVE_ROOTS = asset_serve_roots()

PRINT_TRIM_INCHES = 8.5
PRINT_BLEED_INCHES = 0.125
PRINT_FULL_BLEED_INCHES = PRINT_TRIM_INCHES + (PRINT_BLEED_INCHES * 2)
PRINT_SAFE_MARGIN_INCHES = 0.5
PRINT_DPI = 300
PRINT_REQUIRED_PIXELS = int(PRINT_FULL_BLEED_INCHES * PRINT_DPI)


def ensure_project_dirs() -> None:
    """Create runtime directories used by the app."""
    directories = [
        DATA_DIR,
        DATA_DIR / "imports",
        DATA_DIR / "exports",
        GENERATED_DIR / "prompts",
        GENERATED_DIR / "manifests",
        GENERATED_DIR / "reports",
        GENERATED_DIR / "page_specs",
        ASSETS_DIR / "characters",
        ASSETS_DIR / "environments",
        ASSETS_DIR / "gadgets",
        ASSETS_DIR / "illustrations",
        ASSETS_DIR / "references",
    ]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

