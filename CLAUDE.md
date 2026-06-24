# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Hackster Niko** is a children's book production platform for the "Hackster Niko and the Password Dragon" franchise (ages 5–8, cybersecurity themes). The `hackster_studio/` Python package drives everything: database seeding, AI image-prompt generation, book/movie pipeline automation, and a FastAPI web dashboard.

## Commands

```bash
# Environment setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in ComfyUI/model values

# One-shot dev start (init-db → seed → run)
./run_dev.sh

# Database
python -m hackster_studio.cli init-db
python -m hackster_studio.cli seed

# Book production workflow (in order)
python -m hackster_studio.cli plan-book book01_password_dragon
python -m hackster_studio.cli generate-prompts book01_password_dragon
python -m hackster_studio.cli export-yaml book01_password_dragon
python -m hackster_studio.cli build-book books/book01_password_dragon/book.yaml

# Niko consistency (locked-overlay fallback when no FLUX adapter)
python -m hackster_studio.cli build-niko-lock
HACKSTER_NIKO_LAYER_MODE=locked_overlay python -m hackster_studio.cli compose-niko-lock ...

# Movie pipeline
python -m hackster_studio.cli build-movie-package movies/password_dragon_teaser/movie.yaml

# Print validation
python -m hackster_studio.cli print-check <image_path>

# Web dashboard (http://127.0.0.1:8000)
python -m hackster_studio.cli run

# Linting (ruff is installed; no pyright or CI config yet)
python -m ruff check hackster_studio/ tests/
python -m ruff format --check hackster_studio/ tests/

# Tests
pytest tests/
pytest tests/test_book_planner.py        # single file
pytest tests/test_integration.py -v      # integration (uses TestClient, no live ComfyUI needed)
pytest tests/test_browser.py             # requires pytest-playwright and live_server fixture
```

## Architecture

### Data layer

`hackster_studio/models.py` defines 8 SQLModel tables backed by SQLite (`data/hackster_studio.sqlite3`):

```
Project → Book → Page → Prompt
              ↘ PrintReport
Character, Environment, Gadget   (reference data, seeded once)
```

All timestamps use a `utc_now()` factory. The `Page` model carries the full illustration spec: `page_type`, `niko_layer_mode`, `niko_center_x/y/height`, `text_safe_area`, `hidden_objects_json`, `camera`, `emotion`, `environment`.

### Dual storage — a key gotcha

**Scene state has two independent representations that can diverge:**

1. **SQLite** (`Page` table) — canonical planning data; written by CLI and the Book Generation flow.
2. **JSON scene files** (`storybook_scenes/<slug>/page_NNN.scene.json`) — runtime state for the Story Maker UI; written by `services/story_maker.py`.
3. **YAML page files** (`books/<slug>/pages/page_NNN.yaml`) — written by `services/books.py`; read by `pipeline.py` and `build_book`.
4. **Generated prompts** live in both the Prompt table AND on disk (`data/generated/prompts/` and `books/<slug>/prompts/`).

`book_page_count()` in `story_maker.py` counts YAML files on disk, not DB records — if they get out of sync the UI shows wrong totals. Always push DB changes through to the filesystem via `write_page_yaml` and vice versa.

### Service layer

`hackster_studio/services/` modules handle database CRUD and business logic for each entity (books, pages, characters, etc.). The CLI and FastAPI routes both call these services — never touch the ORM directly from routes or CLI commands.

### Prompt generation

Prompts are Jinja2 templates in `hackster_studio/prompt_templates/*.j2`. The key template is `book_page_illustration.md.j2` — it conditionally includes Niko consistency constraints based on `niko_layer_mode`. Templates receive the full page record as context plus book and character reference data.

Generated prompts land in `data/generated/prompts/pages/<book-slug>/`.

### Automation pipeline

`hackster_studio/automation/pipeline.py` (~850 LOC) owns the monolithic book build:
- `BuildOptions` dataclass controls which stages run (images, PDF, IDML, production PDF)
- `BOOK01_PAGE_PLAN` dict is the canonical 32-page spec (hardcoded in Python; extending to book 2 requires editing this file)
- Calls `comfyui_engine.py` for image generation (HTTP POST → poll → base64 PNG) or falls back to locked-overlay compositing via `niko_lock.py` + `niko_compositor.py`

`automation/movie_pipeline.py` is independent — reads book records, produces shot YAML files in `movies/<movie-slug>/shots/`.

### Web UI and job orchestration

`hackster_studio/main.py` (≈1,450 LOC) is a FastAPI app with Jinja2 HTML templates. It also owns the long-running book generation job system:

- **Two in-memory job stores**: `_jobs` (in `api.py`, for single-image generate jobs) and `_book_generation_jobs` (in `main.py`, for full book builds). Both are module-level dicts protected by a `threading.Lock`; **all jobs are lost on server restart**.
- Book generation runs in a `daemon=True` `threading.Thread` that calls blocking I/O (ComfyUI HTTP, DGX SSH) — it does not participate in the asyncio event loop.
- The web UI polls `/api/book-generation/jobs/{job_id}` for progress updates.

Routes are thin wrappers over service calls. Static assets served at `/static`. `GET /project-assets/{path}` serves any file rooted inside `PROJECT_ROOT` (including `.env` and the SQLite DB — this is a known security hole).

### Key constants — do not paraphrase

`DEFAULT_NIKO_CONSISTENCY` in `automation/pipeline.py` is the canonical Niko character description used in all prompts. Do not rewrite it inline in new templates; import or reference the constant. Same for `DEFAULT_STYLE` and `DEFAULT_HIDDEN_OBJECTS`.

## Key Constants & Specs

**Print specs** (enforced by `config.py` and `automation/quality_checks.py`):
- Trim: 8.5 × 8.5 inches, 300 DPI minimum
- Bleed: 0.125 inches on all sides
- Safe margin: 0.5 inches
- Primary platform: Lulu Direct; future: KDP, IngramSpark

**Hidden objects** (appear on every story page): Golden Gear, Tiny Bug, Blue Crystal, Mini Robot — always include all four in page prompts.

**`niko_layer_mode`** values:
- `full_scene` — Niko generated in-context with the scene (FLUX reference adapter, future)
- `locked_overlay` — Niko rendered separately and composited at fixed `(niko_center_x, niko_base_y)` coordinates; current default

## Asset Naming Convention

```
HN_[Category]_[Subject]_[Descriptor]_[Version].[ext]

Examples:
  HN_Character_Niko_Turnaround_v001.png
  HN_Book01_Page07_Illustration_Color_v003.afdesign
  HN_Book01_PrintInterior_Lulu_FINAL_v003.pdf
```

Version numbers are zero-padded to 3 digits. `FINAL` replaces version suffix only on print-ready exports.

## Output Locations

| Artifact | Path |
|---|---|
| Page prompts | `data/generated/prompts/pages/<book-slug>/` |
| YAML page specs | `data/generated/page_specs/<book-slug>/` |
| Locked Niko composites | `books/<book-slug>/illustrations_locked/` |
| Movie shot packages | `movies/<movie-slug>/shots/` |
| Print reports | SQLite DB (web UI at `/print-validator`) |
| Artwork source | `assets/illustrations/` |

## Environment Variables

Copy `.env.example` to `.env`. Key groups:
- `COMFYUI_*` — server URL, auth, workflow path
- `FLUX_*` / `SDXL_*` — model checkpoints and LoRA paths
- `PRINT_DPI`, `TRIM_*`, `BLEED_*` — override print spec defaults
- `HACKSTER_NIKO_LAYER_MODE` — `full_scene` or `locked_overlay`
- `HACKSTER_SCENE_ROOT` — override scene JSON root (used in tests via `tmp_path`)
- `HACKSTER_STUDIO_DB` — override SQLite path (useful for test isolation)
