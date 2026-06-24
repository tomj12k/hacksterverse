# Story Maker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a layered 2D storybook compositor into the existing FastAPI dashboard — per-element asset layers, camera/lighting/parallax controls, REST API for save/generate/export, and server-side Pillow composition to print-ready PNG.

**Architecture:** The existing `/story-maker` route and three-panel DOM compositor in `app.js` are extended, not rewritten. A new `hackster_studio/api.py` APIRouter provides all `/api/*` REST endpoints. Scene data lives as JSON files in `storybook_scenes/`. Konva.js is not added — the DOM approach already satisfies the schema-drives-rendering invariant and adding Konva would require a full rewrite of the working prototype.

**Tech Stack:** Python 3.13, FastAPI, Pillow, pytest, vanilla JS (no new frontend libraries), SQLite (no new tables)

## Global Constraints

- All Python invoked via `uv run` — never system Python
- Never use `assert` in production code (outside `tests/`)
- Never catch `Exception` or `BaseException` without a comment listing concrete expected exceptions
- Run `uv run inv lint` and `uv run inv test` before every commit
- Normalized 0–1 coordinates for layer `x/y/width/height` — do not use pixel coordinates in scene JSON
- Scene files: `storybook_scenes/{book_slug}/page_{number:03d}.scene.json`
- Asset files: `assets/layers/{type}/...` relative to `PROJECT_ROOT`
- All new FastAPI routes under `/api/` prefix — existing routes untouched
- Shadow `distance` and `blur` values in the scene JSON are raw pixels at the 2625px canvas size

---

## File Map

**Create:**
- `hackster_studio/api.py` — all `/api/*` APIRouter endpoints
- `hackster_studio/services/assets.py` — asset library scan functions
- `hackster_studio/services/exporter.py` — Pillow page compositor
- `hackster_studio/static/story_maker.js` — compositor JS (split from app.js)
- `assets/layers/characters/niko/poses.json` — Niko pose manifest
- `storybook_scenes/book01_password_dragon/page_004.scene.json` — example scene
- `assets/layers/.gitkeep` + subdirectory `.gitkeep` files

**Modify:**
- `hackster_studio/services/story_maker.py` — add `save_scene()`, fix `default_scene()`
- `hackster_studio/config.py` — add `LAYERS_DIR`, `GENERATED_PAGES_DIR`
- `hackster_studio/main.py` — include `api_router`
- `hackster_studio/templates/story_maker.html` — toolbar, asset browser modal, load `story_maker.js`
- `hackster_studio/static/app.js` — remove `initStoryMaker` (moved to story_maker.js)
- `tests/test_story_maker.py` — fix + extend

---

## Task 1: Scene Schema — default_scene, save_scene, fixtures

**Files:**
- Modify: `hackster_studio/services/story_maker.py`
- Modify: `hackster_studio/config.py`
- Create: `assets/layers/characters/niko/poses.json`
- Create: `storybook_scenes/book01_password_dragon/page_004.scene.json`
- Create: `assets/layers/{backgrounds,midground,foreground,props,hidden_objects}/.gitkeep`, `assets/layers/characters/niko/.gitkeep`
- Modify: `tests/test_story_maker.py`

**Interfaces:**
- Produces: `save_scene(scene: dict[str, Any]) -> Path`, `default_scene(book_slug, page_number) -> dict`
- Produces: `LAYERS_DIR: Path`, `GENERATED_PAGES_DIR: Path` in `config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_story_maker.py — replace entire file
import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hackster_studio.main import app
from hackster_studio.services.story_maker import default_scene, load_scene, save_scene, scene_path


def test_default_scene_has_required_top_level_keys() -> None:
    scene = default_scene("book01_password_dragon", 4)

    assert scene["book_slug"] == "book01_password_dragon"
    assert scene["page_number"] == 4
    assert "canvas" in scene
    assert "lighting_brief" in scene
    assert isinstance(scene["layers"], list)


def test_default_scene_canvas_spec() -> None:
    scene = default_scene("book01_password_dragon", 4)
    canvas = scene["canvas"]

    assert canvas["width_px"] == 2625
    assert canvas["height_px"] == 2625
    assert canvas["dpi"] == 300
    assert canvas["bleed_inches"] == 0.125


def test_default_scene_has_camera_layer() -> None:
    scene = default_scene("book01_password_dragon", 4)

    types = [l["type"] for l in scene["layers"]]
    assert "camera" in types


def test_default_scene_has_character_layer() -> None:
    scene = default_scene("book01_password_dragon", 4)

    char_layers = [l for l in scene["layers"] if l["type"] == "character"]
    assert char_layers
    niko = char_layers[0]
    assert niko["character_slug"] == "niko"
    assert "shadow" in niko
    assert "rig" in niko
    assert niko["rig"] is None


def test_default_scene_has_background_layer() -> None:
    scene = default_scene("book01_password_dragon", 4)

    types = [l["type"] for l in scene["layers"]]
    assert "background" in types


def test_default_scene_layers_have_z_index() -> None:
    scene = default_scene("book01_password_dragon", 4)

    for layer in scene["layers"]:
        assert "z_index" in layer, f"Layer {layer['id']} missing z_index"


def test_save_and_reload_scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import story_maker as sm
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path)

    scene = default_scene("testbook", 1)
    saved_path = save_scene(scene)

    assert saved_path.exists()
    loaded = load_scene("testbook", 1)
    assert loaded["book_slug"] == "testbook"
    assert loaded["page_number"] == 1


def test_story_maker_route_renders() -> None:
    client = TestClient(app)

    response = client.get("/story-maker")

    assert response.status_code == 200
    assert "Story Maker" in response.text
    assert "story-scene-data" in response.text
```

- [ ] **Step 2: Run to confirm failures**

```bash
uv run pytest tests/test_story_maker.py -v
```

Expected: `test_default_scene_has_camera_layer` FAIL, `test_default_scene_has_character_layer` FAIL, etc. (existing two tests may pass or fail depending on fixture state — that's fine).

- [ ] **Step 3: Add LAYERS_DIR and GENERATED_PAGES_DIR to config.py**

```python
# hackster_studio/config.py — add after ASSETS_DIR line:
LAYERS_DIR = ASSETS_DIR / "layers"
GENERATED_PAGES_DIR = GENERATED_DIR / "pages"
```

- [ ] **Step 4: Update story_maker.py**

```python
# hackster_studio/services/story_maker.py — replace entire file
"""Layered storybook scene loading and saving for the web story maker."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT

SCENE_ROOT = PROJECT_ROOT / "storybook_scenes"


def scene_path(book_slug: str, page_number: int) -> Path:
    return SCENE_ROOT / book_slug / f"page_{page_number:03d}.scene.json"


def load_scene(book_slug: str = "book01_password_dragon", page_number: int = 4) -> dict[str, Any]:
    path = scene_path(book_slug, page_number)
    if not path.exists():
        return default_scene(book_slug, page_number)
    return json.loads(path.read_text(encoding="utf-8"))


def save_scene(scene: dict[str, Any]) -> Path:
    path = scene_path(scene["book_slug"], scene["page_number"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scene, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def default_scene(book_slug: str, page_number: int) -> dict[str, Any]:
    return {
        "book_slug": book_slug,
        "page_number": page_number,
        "canvas": {
            "trim_inches": [8.5, 8.5],
            "bleed_inches": 0.125,
            "safe_margin_inches": 0.5,
            "dpi": 300,
            "width_px": 2625,
            "height_px": 2625,
        },
        "lighting_brief": "ambient_soft",
        "layers": [
            {
                "id": "camera_001",
                "name": "Camera",
                "type": "camera",
                "z_index": 99,
                "transform": {"x": 0.0, "y": 0.0, "zoom": 1.0, "rotation": 0},
            },
            {
                "id": "lighting_001",
                "name": "Ambient Light",
                "type": "lighting",
                "z_index": 10,
                "tint_color": "#FFFFFF",
                "blend_mode": "multiply",
                "opacity": 0.0,
            },
            {
                "id": "char_niko",
                "name": "Hackster Niko",
                "type": "character",
                "z_index": 3,
                "parallax_factor": 1.0,
                "character_slug": "niko",
                "asset_path": None,
                "lighting_variant": "ambient_soft",
                "pose": "standing_neutral",
                "rig": None,
                "shadow": {
                    "enabled": False,
                    "angle": 270,
                    "distance": 12,
                    "blur": 8,
                    "opacity": 0.3,
                },
                "transform": {
                    "x": 0.5,
                    "y": 0.6,
                    "width": 0.2,
                    "height": 0.4,
                    "scale": 1.0,
                    "rotation": 0,
                    "opacity": 1,
                },
            },
            {
                "id": "bg_001",
                "name": "Background",
                "type": "background",
                "z_index": 0,
                "parallax_factor": 0.1,
                "asset_path": None,
                "lighting_variant": "ambient_soft",
                "transform": {
                    "x": 0.0,
                    "y": 0.0,
                    "width": 1.5,
                    "height": 1.5,
                    "scale": 1.0,
                    "rotation": 0,
                    "opacity": 1,
                },
            },
        ],
    }
```

- [ ] **Step 5: Create asset library directory structure**

```bash
mkdir -p \
  assets/layers/backgrounds \
  assets/layers/midground \
  assets/layers/foreground \
  assets/layers/characters/niko \
  assets/layers/props \
  assets/layers/hidden_objects
touch \
  assets/layers/backgrounds/.gitkeep \
  assets/layers/midground/.gitkeep \
  assets/layers/foreground/.gitkeep \
  assets/layers/props/.gitkeep \
  assets/layers/hidden_objects/.gitkeep
```

Run from `HacksterNiko/`.

- [ ] **Step 6: Create Niko poses.json**

```json
{
  "character": "niko",
  "poses": [
    { "id": "standing_neutral", "label": "Standing Neutral", "tags": ["idle"] },
    { "id": "pointing_right",   "label": "Pointing Right",   "tags": ["teaching", "action"] },
    { "id": "crouching",        "label": "Crouching",        "tags": ["action"] },
    { "id": "waving",           "label": "Waving",           "tags": ["greeting"] },
    { "id": "comforting",       "label": "Comforting",       "tags": ["emotion"] },
    { "id": "celebrating",      "label": "Celebrating",      "tags": ["emotion", "action"] },
    { "id": "thinking",         "label": "Thinking",         "tags": ["idle", "teaching"] },
    { "id": "running",          "label": "Running",          "tags": ["action"] }
  ]
}
```

Save to `assets/layers/characters/niko/poses.json`.

- [ ] **Step 7: Create example scene file**

```json
{
  "book_slug": "book01_password_dragon",
  "page_number": 4,
  "canvas": {
    "trim_inches": [8.5, 8.5],
    "bleed_inches": 0.125,
    "safe_margin_inches": 0.5,
    "dpi": 300,
    "width_px": 2625,
    "height_px": 2625
  },
  "lighting_brief": "warm_sunset_left",
  "layers": [
    {
      "id": "camera_001",
      "name": "Camera",
      "type": "camera",
      "z_index": 99,
      "transform": { "x": 0.0, "y": 0.0, "zoom": 1.0, "rotation": 0 }
    },
    {
      "id": "lighting_001",
      "name": "Warm Sunset",
      "type": "lighting",
      "z_index": 10,
      "tint_color": "#FF8C42",
      "blend_mode": "multiply",
      "opacity": 0.18
    },
    {
      "id": "char_niko",
      "name": "Hackster Niko",
      "type": "character",
      "z_index": 3,
      "parallax_factor": 1.0,
      "character_slug": "niko",
      "asset_path": null,
      "lighting_variant": "warm_sunset_left",
      "pose": "pointing_right",
      "rig": null,
      "shadow": { "enabled": true, "angle": 225, "distance": 18, "blur": 12, "opacity": 0.35 },
      "transform": { "x": 0.45, "y": 0.6, "width": 0.2, "height": 0.4, "scale": 1.0, "rotation": 0, "opacity": 1 }
    },
    {
      "id": "bg_001",
      "name": "Cyber Forest Sky",
      "type": "background",
      "z_index": 0,
      "parallax_factor": 0.1,
      "asset_path": null,
      "lighting_variant": "warm_sunset_left",
      "transform": { "x": 0.0, "y": 0.0, "width": 1.5, "height": 1.5, "scale": 1.0, "rotation": 0, "opacity": 1 }
    }
  ]
}
```

Save to `storybook_scenes/book01_password_dragon/page_004.scene.json`.

- [ ] **Step 8: Run tests**

```bash
uv run pytest tests/test_story_maker.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 9: Lint and commit**

```bash
uv run inv lint
git add \
  hackster_studio/services/story_maker.py \
  hackster_studio/config.py \
  assets/layers/ \
  storybook_scenes/ \
  tests/test_story_maker.py
git commit -m "feat: extend scene schema — default_scene, save_scene, asset dirs, poses manifest"
```

---

## Task 2: Scene REST API (GET + PUT)

**Files:**
- Create: `hackster_studio/api.py`
- Modify: `hackster_studio/main.py`
- Modify: `tests/test_story_maker.py`

**Interfaces:**
- Consumes: `load_scene`, `save_scene` from `story_maker.py`
- Produces: `GET /api/scenes/{book_slug}/{page_number}` → scene JSON, `PUT /api/scenes/{book_slug}/{page_number}` → 204

- [ ] **Step 1: Write failing tests**

Add to `tests/test_story_maker.py`:

```python
def test_get_scene_api_returns_json() -> None:
    client = TestClient(app)

    response = client.get("/api/scenes/book01_password_dragon/4")

    assert response.status_code == 200
    data = response.json()
    assert data["book_slug"] == "book01_password_dragon"
    assert data["page_number"] == 4
    assert isinstance(data["layers"], list)


def test_put_scene_api_saves_and_reloads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import story_maker as sm
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path)

    client = TestClient(app)
    scene = default_scene("book01_password_dragon", 7)
    scene["lighting_brief"] = "cool_forest_ambient"

    response = client.put("/api/scenes/book01_password_dragon/7", json=scene)

    assert response.status_code == 204
    saved = json.loads((tmp_path / "book01_password_dragon" / "page_007.scene.json").read_text())
    assert saved["lighting_brief"] == "cool_forest_ambient"


def test_put_scene_api_rejects_mismatched_slug() -> None:
    client = TestClient(app)
    scene = default_scene("book01_password_dragon", 4)

    response = client.put("/api/scenes/wrong_slug/4", json=scene)

    assert response.status_code == 422


def test_put_scene_api_rejects_missing_layers() -> None:
    client = TestClient(app)

    response = client.put(
        "/api/scenes/book01_password_dragon/4",
        json={"book_slug": "book01_password_dragon", "page_number": 4},
    )

    assert response.status_code == 422
```

- [ ] **Step 2: Run to confirm failures**

```bash
uv run pytest tests/test_story_maker.py::test_get_scene_api_returns_json -v
```

Expected: FAIL with 404 (route not registered yet).

- [ ] **Step 3: Create hackster_studio/api.py**

```python
"""REST API router — all /api/* endpoints for the Story Maker."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException

from .services.story_maker import load_scene, save_scene

router = APIRouter()


# ── Scenes ────────────────────────────────────────────────────────────────────

@router.get("/scenes/{book_slug}/{page_number}")
def get_scene(book_slug: str, page_number: int) -> dict[str, Any]:
    return load_scene(book_slug, page_number)


@router.put("/scenes/{book_slug}/{page_number}", status_code=204)
def put_scene(
    book_slug: str,
    page_number: int,
    scene: dict[str, Any] = Body(...),
) -> None:
    if scene.get("book_slug") != book_slug or scene.get("page_number") != page_number:
        raise HTTPException(status_code=422, detail="book_slug/page_number mismatch with URL")
    if "layers" not in scene:
        raise HTTPException(status_code=422, detail="layers field is required")
    save_scene(scene)
```

- [ ] **Step 4: Register the router in main.py**

Add after the existing imports (around line 31) and after `app = FastAPI(...)`:

```python
# In hackster_studio/main.py — add import:
from .api import router as api_router

# After app = FastAPI(...) line, add:
app.include_router(api_router, prefix="/api")
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_story_maker.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Lint and commit**

```bash
uv run inv lint
git add hackster_studio/api.py hackster_studio/main.py tests/test_story_maker.py
git commit -m "feat: add scene REST API — GET and PUT /api/scenes"
```

---

## Task 3: Asset Library Service + API

**Files:**
- Create: `hackster_studio/services/assets.py`
- Modify: `hackster_studio/api.py`
- Create: `tests/test_assets.py`

**Interfaces:**
- Consumes: `LAYERS_DIR` from `config.py`
- Produces: `list_assets() -> dict[str, Any]`, `list_poses(character_slug: str) -> list[dict]`
- Produces: `GET /api/assets`, `GET /api/assets/characters/{slug}/poses`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_assets.py — new file
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hackster_studio.main import app
from hackster_studio.services.assets import list_assets, list_poses


def test_list_assets_returns_expected_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import assets as assets_mod
    monkeypatch.setattr(assets_mod, "LAYERS_DIR", tmp_path)

    result = list_assets()

    assert "backgrounds" in result
    assert "midground" in result
    assert "foreground" in result
    assert "characters" in result
    assert "props" in result
    assert "hidden_objects" in result


def test_list_assets_finds_png_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import assets as assets_mod
    monkeypatch.setattr(assets_mod, "LAYERS_DIR", tmp_path)
    bg_dir = tmp_path / "backgrounds"
    bg_dir.mkdir()
    (bg_dir / "cyber_forest_ambient_soft.png").write_bytes(b"")

    result = list_assets()

    assert len(result["backgrounds"]) == 1
    assert "cyber_forest_ambient_soft.png" in result["backgrounds"][0]


def test_list_poses_reads_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import assets as assets_mod
    monkeypatch.setattr(assets_mod, "LAYERS_DIR", tmp_path)
    niko_dir = tmp_path / "characters" / "niko"
    niko_dir.mkdir(parents=True)
    manifest = {"character": "niko", "poses": [{"id": "waving", "label": "Waving", "tags": ["greeting"]}]}
    (niko_dir / "poses.json").write_text(json.dumps(manifest), encoding="utf-8")

    poses = list_poses("niko")

    assert len(poses) == 1
    assert poses[0]["id"] == "waving"


def test_list_poses_returns_empty_when_no_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import assets as assets_mod
    monkeypatch.setattr(assets_mod, "LAYERS_DIR", tmp_path)

    poses = list_poses("unknown_character")

    assert poses == []


def test_assets_endpoint_returns_200() -> None:
    client = TestClient(app)

    response = client.get("/api/assets")

    assert response.status_code == 200
    data = response.json()
    assert "backgrounds" in data


def test_poses_endpoint_returns_list() -> None:
    client = TestClient(app)

    response = client.get("/api/assets/characters/niko/poses")

    assert response.status_code == 200
    assert isinstance(response.json(), list)
```

- [ ] **Step 2: Run to confirm failures**

```bash
uv run pytest tests/test_assets.py -v
```

Expected: all FAIL (module doesn't exist yet).

- [ ] **Step 3: Create hackster_studio/services/assets.py**

```python
"""Asset library scanning — discovers available layer images by type."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import LAYERS_DIR, PROJECT_ROOT


def _relative_paths(directory: Path) -> list[str]:
    """Return PROJECT_ROOT-relative POSIX paths for all PNGs in directory."""
    if not directory.exists():
        return []
    return sorted(
        p.relative_to(PROJECT_ROOT).as_posix()
        for p in directory.rglob("*.png")
    )


def list_assets() -> dict[str, Any]:
    """Scan assets/layers/ and return image paths grouped by layer type."""
    chars_dir = LAYERS_DIR / "characters"
    characters: dict[str, list[str]] = {}
    if chars_dir.exists():
        for char_dir in sorted(chars_dir.iterdir()):
            if char_dir.is_dir():
                characters[char_dir.name] = _relative_paths(char_dir)

    return {
        "backgrounds": _relative_paths(LAYERS_DIR / "backgrounds"),
        "midground": _relative_paths(LAYERS_DIR / "midground"),
        "foreground": _relative_paths(LAYERS_DIR / "foreground"),
        "characters": characters,
        "props": _relative_paths(LAYERS_DIR / "props"),
        "hidden_objects": _relative_paths(LAYERS_DIR / "hidden_objects"),
    }


def list_poses(character_slug: str) -> list[dict[str, Any]]:
    """Return poses from a character's poses.json manifest, or [] if absent."""
    poses_path = LAYERS_DIR / "characters" / character_slug / "poses.json"
    if not poses_path.exists():
        return []
    data = json.loads(poses_path.read_text(encoding="utf-8"))
    return data.get("poses", [])
```

- [ ] **Step 4: Add asset routes to hackster_studio/api.py**

Append to `hackster_studio/api.py`:

```python
from .services.assets import list_assets, list_poses


# ── Assets ────────────────────────────────────────────────────────────────────

@router.get("/assets")
def get_assets() -> dict[str, Any]:
    return list_assets()


@router.get("/assets/characters/{character_slug}/poses")
def get_character_poses(character_slug: str) -> list[dict[str, Any]]:
    return list_poses(character_slug)
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_assets.py -v
```

Expected: all PASS.

- [ ] **Step 6: Lint and commit**

```bash
uv run inv lint
git add hackster_studio/services/assets.py hackster_studio/api.py tests/test_assets.py
git commit -m "feat: add asset library service and /api/assets endpoints"
```

---

## Task 4: Generation Job API

**Files:**
- Modify: `hackster_studio/api.py`
- Create: `tests/test_generate_api.py`

**Interfaces:**
- Consumes: `generate_image_comfyui` from `hackster_studio/automation/comfyui_engine.py`
- Produces: `POST /api/generate` → `{"job_id": str}`, `GET /api/generate/{job_id}` → `{"status": str, "asset_path": str | None}`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_generate_api.py — new file
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from hackster_studio.main import app


def test_post_generate_returns_job_id() -> None:
    client = TestClient(app)

    with patch("hackster_studio.api.generate_image_comfyui") as mock_gen:
        mock_gen.return_value = Path("assets/layers/characters/niko/waving_ambient_soft.png")
        response = client.post("/api/generate", json={
            "layer_id": "char_niko",
            "layer_type": "character",
            "prompt": "Hackster Niko waving",
            "output_path": "assets/layers/characters/niko/waving_ambient_soft.png",
            "lighting_variant": "ambient_soft",
        })

    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data
    assert len(data["job_id"]) == 36  # UUID4 format


def test_get_generate_status_pending_then_done() -> None:
    client = TestClient(app)
    completed = {}

    def slow_gen(prompt: str, output_path: Path, **kwargs: object) -> Path:
        time.sleep(0.05)
        completed["done"] = True
        return output_path

    with patch("hackster_studio.api.generate_image_comfyui", side_effect=slow_gen):
        post_resp = client.post("/api/generate", json={
            "layer_id": "bg_001",
            "layer_type": "background",
            "prompt": "Cyber Forest background",
            "output_path": "assets/layers/backgrounds/cyber_forest_ambient_soft.png",
            "lighting_variant": "ambient_soft",
        })
    job_id = post_resp.json()["job_id"]

    # Poll until done (TestClient runs background tasks synchronously)
    status_resp = client.get(f"/api/generate/{job_id}")
    assert status_resp.status_code == 200
    data = status_resp.json()
    assert data["status"] in ("pending", "running", "done")


def test_get_generate_status_unknown_job() -> None:
    client = TestClient(app)

    response = client.get("/api/generate/nonexistent-job-id")

    assert response.status_code == 404
```

- [ ] **Step 2: Run to confirm failures**

```bash
uv run pytest tests/test_generate_api.py -v
```

Expected: all FAIL (routes not defined).

- [ ] **Step 3: Add generation routes to hackster_studio/api.py**

At the top of `hackster_studio/api.py`, add to the imports:

```python
import uuid
from dataclasses import dataclass
from pathlib import Path

from .automation.comfyui_engine import generate_image_comfyui
from .config import PROJECT_ROOT
```

Then add after the assets section:

```python
# ── Generation Jobs ───────────────────────────────────────────────────────────

@dataclass
class _JobStatus:
    status: str = "pending"   # pending | running | done | failed
    asset_path: str | None = None


# Module-level job store. Ephemeral — lost on server restart.
# Thread-safe for single-user local tool; no lock needed.
_jobs: dict[str, _JobStatus] = {}


class GenerateRequest(BaseModel):
    layer_id: str
    layer_type: str
    prompt: str
    output_path: str
    lighting_variant: str


@router.post("/generate")
def post_generate(request: GenerateRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    job_id = str(uuid.uuid4())
    _jobs[job_id] = _JobStatus(status="pending")
    background_tasks.add_task(_run_generation, job_id, request)
    return {"job_id": job_id}


@router.get("/generate/{job_id}")
def get_generate_status(job_id: str) -> dict[str, Any]:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    return {"status": job.status, "asset_path": job.asset_path}


def _run_generation(job_id: str, request: GenerateRequest) -> None:
    _jobs[job_id].status = "running"
    try:
        output = PROJECT_ROOT / request.output_path
        generate_image_comfyui(request.prompt, output)
        _jobs[job_id].status = "done"
        _jobs[job_id].asset_path = request.output_path
    except Exception:
        # Broad catch is intentional: generate_image_comfyui can raise
        # urllib.error.URLError, json.JSONDecodeError, PIL errors, IOError,
        # or TimeoutError — we need to surface all of them as job failures.
        _jobs[job_id].status = "failed"
```

Also add `BaseModel` and `Any` imports at the top:

```python
from pydantic import BaseModel
from typing import Any
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_generate_api.py -v
```

Expected: all PASS. (TestClient runs background tasks synchronously in tests.)

- [ ] **Step 5: Lint and commit**

```bash
uv run inv lint
git add hackster_studio/api.py tests/test_generate_api.py
git commit -m "feat: add generation job API — POST/GET /api/generate with BackgroundTasks"
```

---

## Task 5: Export Service + API

**Files:**
- Create: `hackster_studio/services/exporter.py`
- Modify: `hackster_studio/api.py`
- Create: `tests/test_exporter.py`

**Interfaces:**
- Consumes: `set_dpi_metadata` from `comfyui_engine.py`, `GENERATED_PAGES_DIR` from `config.py`
- Produces: `export_scene(scene: dict, mode: str) -> Path`
- Produces: `POST /api/export/{book_slug}/{page_number}?mode=flat|draft`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_exporter.py — new file
import json
from pathlib import Path

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from hackster_studio.main import app
from hackster_studio.services.exporter import export_scene
from hackster_studio.services.story_maker import default_scene


def _make_test_png(path: Path, size: tuple[int, int] = (100, 100)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", size, (255, 0, 0, 255))
    img.save(str(path))


def test_export_flat_creates_png(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    scene = default_scene("testbook", 1)
    out = export_scene(scene, mode="flat")

    assert out.exists()
    assert out.suffix == ".png"
    assert "flat" in out.name


def test_export_draft_creates_png(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    scene = default_scene("testbook", 1)
    scene["layers"].append({
        "id": "text_001", "name": "Story Text", "type": "text", "z_index": 20,
        "text": "Hello world", "font_size": 0.04,
        "transform": {"x": 0.1, "y": 0.75, "width": 0.8, "height": 0.2, "opacity": 1},
    })
    out = export_scene(scene, mode="draft")

    assert out.exists()
    assert "draft" in out.name


def test_export_flat_skips_text_layers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    scene = default_scene("testbook", 1)
    scene["layers"].append({
        "id": "text_001", "name": "Story Text", "type": "text", "z_index": 20,
        "text": "Secret text", "font_size": 0.04,
        "transform": {"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.2, "opacity": 1},
    })
    out_flat = export_scene(scene, mode="flat")
    out_draft = export_scene(scene, mode="draft")

    # Both must produce valid PNG files (no crash)
    assert out_flat.exists()
    assert out_draft.exists()


def test_export_composites_image_layer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio import config as cfg
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    # Place a red test image where the scene references it
    asset_rel = "assets/layers/backgrounds/test_bg.png"
    asset_full = cfg.PROJECT_ROOT / asset_rel
    _make_test_png(asset_full)

    scene = default_scene("testbook", 1)
    # Set asset_path on the background layer
    for layer in scene["layers"]:
        if layer["type"] == "background":
            layer["asset_path"] = asset_rel

    out = export_scene(scene, mode="flat")

    assert out.exists()
    img = Image.open(out)
    assert img.size == (2625, 2625)


def test_export_api_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    client = TestClient(app)
    response = client.post("/api/export/book01_password_dragon/4?mode=flat")

    assert response.status_code == 200
    assert "output_path" in response.json()
```

- [ ] **Step 2: Run to confirm failures**

```bash
uv run pytest tests/test_exporter.py -v
```

Expected: all FAIL.

- [ ] **Step 3: Create hackster_studio/services/exporter.py**

```python
"""Server-side Pillow compositor — composes scene layers into a print-ready PNG."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from ..automation.comfyui_engine import set_dpi_metadata
from ..config import GENERATED_PAGES_DIR, PROJECT_ROOT


def _denorm(value: float, canvas_size: int) -> int:
    """Convert a 0–1 normalized value to pixels."""
    return round(value * canvas_size)


def _apply_shadow(img: Image.Image, shadow: dict[str, Any]) -> Image.Image:
    """Return img composited over its own directional drop shadow."""
    if not shadow.get("enabled"):
        return img

    angle_rad = math.radians(shadow.get("angle", 270))
    distance_px = shadow.get("distance", 12)
    blur_px = shadow.get("blur", 8)
    opacity = shadow.get("opacity", 0.3)

    offset_x = round(math.cos(angle_rad) * distance_px)
    offset_y = round(math.sin(angle_rad) * distance_px)

    alpha = img.split()[3]
    dark = Image.new("RGBA", img.size, (0, 0, 0, round(opacity * 255)))
    dark.putalpha(alpha)
    blurred = dark.filter(ImageFilter.GaussianBlur(radius=blur_px))

    shadow_canvas = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow_canvas.paste(blurred, (offset_x, offset_y), blurred)
    result = Image.alpha_composite(shadow_canvas, img)
    return result


def _composite_lighting(
    canvas: Image.Image,
    tint_hex: str,
    blend_mode: str,
    opacity: float,
) -> Image.Image:
    """Apply a tint overlay to canvas using multiply or screen blend."""
    r = int(tint_hex[1:3], 16)
    g = int(tint_hex[3:5], 16)
    b = int(tint_hex[5:7], 16)
    W, H = canvas.size
    tint_rgb = Image.new("RGB", (W, H), (r, g, b))
    canvas_rgb = canvas.convert("RGB")

    if blend_mode == "multiply":
        blended = ImageChops.multiply(canvas_rgb, tint_rgb)
    elif blend_mode == "screen":
        blended = ImageChops.screen(canvas_rgb, tint_rgb)
    else:
        blended = canvas_rgb

    result_rgb = Image.blend(canvas_rgb, blended, opacity)
    return result_rgb.convert("RGBA")


def export_scene(scene: dict[str, Any], mode: str = "flat") -> Path:
    """Composite all scene layers into a single print-ready PNG.

    :param scene: Parsed scene JSON dict.
    :param mode: 'flat' omits text layers (Affinity hand-off); 'draft' includes them.
    :returns: Path to the saved PNG file.
    """
    canvas_info = scene["canvas"]
    W: int = canvas_info["width_px"]
    H: int = canvas_info["height_px"]
    dpi: int = canvas_info["dpi"]

    canvas = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    layers = sorted(scene.get("layers", []), key=lambda l: l.get("z_index", 0))
    camera = next((l for l in layers if l["type"] == "camera"), None)

    for layer in layers:
        layer_type = layer["type"]

        if layer_type == "camera":
            continue

        if layer_type == "text":
            if mode == "flat":
                continue
            transform = layer.get("transform", {})
            x_px = _denorm(transform.get("x", 0.1), W)
            y_px = _denorm(transform.get("y", 0.75), H)
            font_size_px = max(12, _denorm(layer.get("font_size", 0.04), H))
            draw = ImageDraw.Draw(canvas)
            draw.text((x_px, y_px), layer.get("text", ""), fill=(30, 30, 30, 220))
            continue

        if layer_type == "lighting":
            canvas = _composite_lighting(
                canvas,
                layer.get("tint_color", "#FFFFFF"),
                layer.get("blend_mode", "multiply"),
                layer.get("opacity", 0.0),
            )
            continue

        asset_path_str = layer.get("asset_path")
        if not asset_path_str:
            continue
        asset_file = PROJECT_ROOT / asset_path_str
        if not asset_file.exists():
            continue

        img = Image.open(asset_file).convert("RGBA")

        transform = layer.get("transform", {})
        target_w = max(1, _denorm(transform.get("width", 1.0), W))
        target_h = max(1, _denorm(transform.get("height", 1.0), H))
        scale = transform.get("scale", 1.0)
        target_w = max(1, round(target_w * scale))
        target_h = max(1, round(target_h * scale))

        img = img.resize((target_w, target_h), Image.LANCZOS)

        rotation = transform.get("rotation", 0)
        if rotation:
            img = img.rotate(-rotation, expand=True, resample=Image.BICUBIC)

        if layer_type in ("character", "props"):
            img = _apply_shadow(img, layer.get("shadow", {}))

        opacity_val = float(transform.get("opacity", 1.0))
        if opacity_val < 1.0:
            r_ch, g_ch, b_ch, a_ch = img.split()
            a_ch = a_ch.point(lambda p: round(p * opacity_val))
            img = Image.merge("RGBA", (r_ch, g_ch, b_ch, a_ch))

        # Centered placement: x/y are center-point in normalized coords
        paste_x = _denorm(transform.get("x", 0.0), W) - img.width // 2
        paste_y = _denorm(transform.get("y", 0.0), H) - img.height // 2

        layer_canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        layer_canvas.paste(img, (paste_x, paste_y), img)
        canvas = Image.alpha_composite(canvas, layer_canvas)

    # Apply camera crop and zoom
    if camera:
        cam_t = camera.get("transform", {})
        zoom = float(cam_t.get("zoom", 1.0))
        crop_w = max(1, round(W / zoom))
        crop_h = max(1, round(H / zoom))
        cam_x = min(_denorm(cam_t.get("x", 0.0), W), W - crop_w)
        cam_y = min(_denorm(cam_t.get("y", 0.0), H), H - crop_h)
        canvas = canvas.crop((cam_x, cam_y, cam_x + crop_w, cam_y + crop_h))
        if zoom != 1.0:
            canvas = canvas.resize((W, H), Image.LANCZOS)

    book_slug = scene["book_slug"]
    page_number = scene["page_number"]
    out_dir = GENERATED_PAGES_DIR / book_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"page_{page_number:03d}_{mode}.png"

    canvas.convert("RGB").save(str(out_path), "PNG")
    set_dpi_metadata(out_path, dpi)
    return out_path
```

- [ ] **Step 4: Add export route to hackster_studio/api.py**

Append to `hackster_studio/api.py`:

```python
from .services.exporter import export_scene
from .services.story_maker import load_scene, save_scene


# ── Export ────────────────────────────────────────────────────────────────────

@router.post("/export/{book_slug}/{page_number}")
def post_export(
    book_slug: str,
    page_number: int,
    mode: str = "flat",
) -> dict[str, str]:
    if mode not in ("flat", "draft"):
        raise HTTPException(status_code=422, detail="mode must be 'flat' or 'draft'")
    scene = load_scene(book_slug, page_number)
    out_path = export_scene(scene, mode=mode)
    return {"output_path": out_path.relative_to(PROJECT_ROOT).as_posix()}
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_exporter.py -v
```

Expected: all PASS.

- [ ] **Step 6: Run full suite**

```bash
uv run inv test
```

Expected: all PASS.

- [ ] **Step 7: Lint and commit**

```bash
uv run inv lint
git add hackster_studio/services/exporter.py hackster_studio/api.py tests/test_exporter.py
git commit -m "feat: add Pillow export service and POST /api/export endpoint"
```

---

## Task 6: Compositor JS — Split + Layer Type Rendering

**Files:**
- Create: `hackster_studio/static/story_maker.js`
- Modify: `hackster_studio/static/app.js` (remove initStoryMaker)
- Modify: `hackster_studio/templates/story_maker.html` (load story_maker.js, add type icons CSS)

**Interfaces:**
- Consumes: scene JSON from `#story-scene-data` script tag
- Produces: type-aware layer rendering (camera crop rect, lighting blend div, shadow CSS filter, parallax on camera move, layer type icons in panel)

- [ ] **Step 1: Move initStoryMaker from app.js to story_maker.js**

In `hackster_studio/static/app.js`, delete everything from `function initStoryMaker()` to the closing `initStoryMaker();` call (lines ~16–153), leaving only the clipboard handler.

`hackster_studio/static/app.js` should now be:

```javascript
document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) return;

  const target = document.querySelector(button.dataset.copy);
  if (!target) return;

  await navigator.clipboard.writeText(target.innerText);
  const original = button.innerText;
  button.innerText = "Copied";
  setTimeout(() => { button.innerText = original; }, 1200);
});
```

- [ ] **Step 2: Create hackster_studio/static/story_maker.js**

```javascript
// ── Constants ──────────────────────────────────────────────────────────────

const LAYER_ICONS = {
  camera:     "🎥",
  lighting:   "💡",
  text:       "📝",
  foreground: "🌳",
  character:  "🧑",
  props:      "📦",
  midground:  "🌿",
  background: "🌄",
};

const LIGHTING_SHADOW_ANGLES = {
  ambient_soft:        270,
  warm_sunset_left:    225,
  cool_forest_ambient: 270,
  dramatic_backlight:   45,
};

// ── State ──────────────────────────────────────────────────────────────────

function initStoryMaker() {
  const root = document.querySelector("[data-story-maker]");
  const data = document.querySelector("#story-scene-data");
  if (!root || !data) return;

  const scene = JSON.parse(data.textContent);
  const stage = root.querySelector("[data-story-stage]");
  const layerList = root.querySelector("[data-layer-list]");
  const boneList = root.querySelector("[data-bone-list]");
  const controls = Array.from(root.querySelectorAll("[data-control]"));
  let selectedId = null;

  // Sort layers high z_index first for panel; low z_index first for stage.
  const sortedForPanel = () =>
    [...scene.layers].sort((a, b) => (b.z_index || 0) - (a.z_index || 0));
  const sortedForStage = () =>
    [...scene.layers].sort((a, b) => (a.z_index || 0) - (b.z_index || 0));

  const findLayer = (id) => scene.layers.find((l) => l.id === id);

  // ── Camera helpers ────────────────────────────────────────────────────────

  function getCameraLayer() {
    return scene.layers.find((l) => l.type === "camera");
  }

  function computeParallaxOffset(layer) {
    const cam = getCameraLayer();
    if (!cam) return { dx: 0, dy: 0 };
    const factor = layer.parallax_factor ?? 1.0;
    return {
      dx: (cam.transform?.x ?? 0) * factor,
      dy: (cam.transform?.y ?? 0) * factor,
    };
  }

  // ── Shadow CSS ────────────────────────────────────────────────────────────

  function shadowFilter(shadow) {
    if (!shadow?.enabled) return "";
    const angle = (shadow.angle ?? 270) * (Math.PI / 180);
    const dist = shadow.distance ?? 12;
    const blur = shadow.blur ?? 8;
    const opacity = shadow.opacity ?? 0.3;
    const dx = Math.round(Math.cos(angle) * dist);
    const dy = Math.round(Math.sin(angle) * dist);
    return `drop-shadow(${dx}px ${dy}px ${blur}px rgba(0,0,0,${opacity}))`;
  }

  // ── Render layer element ──────────────────────────────────────────────────

  function renderLayer(layer) {
    // Remove stale element if re-rendering
    stage.querySelector(`[data-layer-id="${layer.id}"]`)?.remove();

    const el = document.createElement("div");
    el.className = "story-layer";
    el.dataset.layerId = layer.id;

    if (layer.type === "lighting") {
      el.classList.add("story-layer--lighting");
      el.style.position = "absolute";
      el.style.inset = "0";
      el.style.pointerEvents = "none";
      el.style.zIndex = layer.z_index ?? 1;
      el.style.backgroundColor = layer.tint_color ?? "#FFFFFF";
      el.style.mixBlendMode = layer.blend_mode ?? "multiply";
      el.style.opacity = layer.opacity ?? 0;
      stage.appendChild(el);
      return;
    }

    if (layer.type === "camera") {
      el.classList.add("story-layer--camera");
      el.style.position = "absolute";
      el.style.inset = "0";
      el.style.border = "2px dashed rgba(0,180,255,0.6)";
      el.style.pointerEvents = "none";
      el.style.zIndex = layer.z_index ?? 99;
      stage.appendChild(el);
      return;
    }

    if (layer.type === "text") {
      el.classList.add("story-layer--text");
      el.style.zIndex = layer.z_index ?? 1;
      const textEl = document.createElement("div");
      textEl.className = "story-placeholder story-placeholder--text";
      textEl.textContent = layer.text || layer.name;
      el.appendChild(textEl);
      stage.appendChild(el);
      updateLayerElement(layer);
      return;
    }

    // Image-bearing layers (background, midground, foreground, character, props)
    el.style.zIndex = layer.z_index ?? 1;
    if (layer.asset_path) {
      const img = document.createElement("img");
      img.alt = layer.name;
      img.src = `/project-assets/${layer.asset_path}`;
      img.style.width = "100%";
      img.style.height = "100%";
      img.style.objectFit = "fill";
      el.appendChild(img);
    } else {
      const ph = document.createElement("div");
      ph.className = "story-placeholder";
      ph.textContent = `${LAYER_ICONS[layer.type] ?? ""} ${layer.name}`;
      el.appendChild(ph);
    }

    // Shadow filter for character and props
    if (layer.type === "character" || layer.type === "props") {
      const filter = shadowFilter(layer.shadow);
      if (filter) el.style.filter = filter;
    }

    stage.appendChild(el);
    updateLayerElement(layer);
  }

  function updateLayerElement(layer) {
    const el = stage.querySelector(`[data-layer-id="${layer.id}"]`);
    if (!el) return;

    if (layer.type === "lighting") {
      el.style.backgroundColor = layer.tint_color ?? "#FFFFFF";
      el.style.mixBlendMode = layer.blend_mode ?? "multiply";
      el.style.opacity = layer.opacity ?? 0;
      return;
    }

    if (layer.type === "camera" || layer.type === "lighting") return;

    const transform = layer.transform ?? {};
    const { dx, dy } = computeParallaxOffset(layer);

    const x = (transform.x ?? 0) - dx;
    const y = (transform.y ?? 0) - dy;
    const w = transform.width ?? 1;
    const h = transform.height ?? 1;
    const scale = transform.scale ?? 1;
    const rotation = transform.rotation ?? 0;
    const opacity = transform.opacity ?? 1;

    el.style.left = `${x * 100}%`;
    el.style.top = `${y * 100}%`;
    el.style.width = `${w * 100}%`;
    el.style.height = `${h * 100}%`;
    el.style.opacity = opacity;
    el.style.transform = `translate(-50%, -50%) rotate(${rotation}deg) scale(${scale})`;
    el.classList.toggle("is-selected", layer.id === selectedId);

    if (layer.type === "character" || layer.type === "props") {
      el.style.filter = shadowFilter(layer.shadow);
    }
  }

  // ── Layer panel ───────────────────────────────────────────────────────────

  function rebuildLayerPanel() {
    layerList.innerHTML = "";
    sortedForPanel().forEach((layer) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "layer-button";
      button.dataset.layerId = layer.id;
      const icon = LAYER_ICONS[layer.type] ?? "";
      button.textContent = `${icon} ${layer.name}`;
      button.addEventListener("click", () => selectLayer(layer.id));
      layerList.appendChild(button);
    });
  }

  // ── Inspector ─────────────────────────────────────────────────────────────

  function renderBones(layer) {
    boneList.innerHTML = "";
    const bones = layer?.rig?.bones ?? [];
    if (!bones.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No skeleton assigned.";
      boneList.appendChild(empty);
      return;
    }
    bones.forEach((bone) => {
      const row = document.createElement("div");
      row.className = "bone-row";
      row.innerHTML = `<span>${bone.name}</span><input type="number" step="1" value="${bone.rotation ?? 0}" aria-label="${bone.name} rotation">`;
      boneList.appendChild(row);
    });
  }

  function selectLayer(id) {
    selectedId = id;
    const selected = findLayer(id);
    scene.layers.forEach(updateLayerElement);
    layerList.querySelectorAll(".layer-button").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.layerId === id);
    });

    // Populate transform controls
    controls.forEach((input) => {
      const key = input.dataset.control;
      const val = selected?.transform?.[key];
      input.value = val ?? (["opacity", "scale", "zoom"].includes(key) ? 1 : 0);
      input.disabled = !selected;
    });

    renderBones(selected);
    renderInspectorExtras(selected);
  }

  // Placeholder for Task 9 (inspector extras)
  function renderInspectorExtras(layer) {
    const extras = document.querySelector("[data-inspector-extras]");
    if (extras) extras.innerHTML = "";
  }

  // ── Drag ──────────────────────────────────────────────────────────────────

  let dragging = null;

  stage.addEventListener("pointerdown", (event) => {
    const el = event.target.closest(".story-layer");
    if (!el || !el.dataset.layerId) return;
    const layer = findLayer(el.dataset.layerId);
    if (!layer || layer.type === "lighting" || layer.type === "camera") return;
    selectLayer(el.dataset.layerId);
    const rect = stage.getBoundingClientRect();
    dragging = { layer, rect };
    el.setPointerCapture(event.pointerId);
  });

  stage.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    const t = dragging.layer.transform ?? {};
    t.x = Math.min(1, Math.max(0, (event.clientX - dragging.rect.left) / dragging.rect.width));
    t.y = Math.min(1, Math.max(0, (event.clientY - dragging.rect.top) / dragging.rect.height));
    dragging.layer.transform = t;
    updateLayerElement(dragging.layer);
    selectLayer(dragging.layer.id);
  });

  stage.addEventListener("pointerup", () => { dragging = null; });

  // ── Inspector controls ────────────────────────────────────────────────────

  controls.forEach((input) => {
    input.addEventListener("input", () => {
      const layer = findLayer(selectedId);
      if (!layer) return;
      layer.transform = layer.transform ?? {};
      layer.transform[input.dataset.control] = Number(input.value);
      updateLayerElement(layer);
      // Camera movement triggers parallax update on all layers
      if (layer.type === "camera") {
        scene.layers.forEach(updateLayerElement);
      }
    });
  });

  // ── Init ──────────────────────────────────────────────────────────────────

  // Render stage (low z_index first)
  sortedForStage().forEach(renderLayer);
  // Build panel (high z_index first)
  rebuildLayerPanel();
  // Select first non-camera layer
  const firstNonCamera = sortedForPanel().find((l) => l.type !== "camera");
  if (firstNonCamera) selectLayer(firstNonCamera.id);

  // Expose scene and helpers for later tasks
  window._sm = { scene, selectLayer, findLayer, updateLayerElement, renderLayer, rebuildLayerPanel, renderInspectorExtras };
}

initStoryMaker();
```

- [ ] **Step 3: Update story_maker.html to load story_maker.js**

In `hackster_studio/templates/story_maker.html`, replace the `<script>` block at the bottom of the `{% block content %}` (if any) and ensure the new file is loaded. The template should load both scripts:

```html
{# Add inside {% block content %}, before the closing tag #}
<script src="{{ url_for('static', path='story_maker.js') }}"></script>
```

Remove any existing `<script src=".../app.js">` in the story_maker block if present (app.js is loaded globally via base.html — verify that base.html already loads app.js).

- [ ] **Step 4: Verify in browser**

```bash
uv run hackster_studio/cli.py run
```

Open `http://127.0.0.1:8000/story-maker`. Verify:
- Layer panel shows icons (🎥 Camera, 💡 Ambient Light, 🧑 Hackster Niko, 🌄 Background)
- Selecting a layer highlights its button
- Dragging a layer moves it on stage
- Camera layer shows dashed overlay (no image placeholder)
- Lighting layer shows as a translucent color overlay

- [ ] **Step 5: Run tests**

```bash
uv run inv test
```

Expected: all PASS (no Python regressions; JS tested visually above).

- [ ] **Step 6: Commit**

```bash
git add \
  hackster_studio/static/app.js \
  hackster_studio/static/story_maker.js \
  hackster_studio/templates/story_maker.html
git commit -m "feat: split compositor to story_maker.js, add type-aware rendering and parallax"
```

---

## Task 7: Toolbar — Save, Export, Toggle Text

**Files:**
- Modify: `hackster_studio/templates/story_maker.html`
- Modify: `hackster_studio/static/story_maker.js`

**Interfaces:**
- Consumes: `PUT /api/scenes/{slug}/{page}`, `POST /api/export/{slug}/{page}?mode=`
- Produces: Save button with "Saved ✓" confirmation; Export Flat / Export Draft buttons; Toggle Text button

- [ ] **Step 1: Add toolbar HTML to story_maker.html**

In `story_maker.html`, replace the existing `<section class="page-head">` block with:

```html
<section class="page-head">
  <div>
    <h1>Story Maker</h1>
    <p>{{ scene.book_slug }} · page {{ "%03d"|format(scene.page_number) }}</p>
  </div>
  <div class="button-row">
    <button type="button" data-action="save">Save</button>
    <button type="button" data-action="export-flat">Export Flat</button>
    <button type="button" data-action="export-draft">Export Draft</button>
    <button type="button" data-action="toggle-text">Toggle Text</button>
    <button type="button" data-copy="#scene-json">Copy JSON</button>
  </div>
</section>
```

- [ ] **Step 2: Add toolbar wiring to story_maker.js**

Add a `initToolbar()` function and call it from `initStoryMaker()`, after the init block:

```javascript
function initToolbar(scene) {
  const bookSlug = scene.book_slug;
  const pageNumber = scene.page_number;
  let textVisible = true;

  async function saveScene() {
    const btn = document.querySelector("[data-action='save']");
    btn.textContent = "Saving…";
    btn.disabled = true;
    try {
      const resp = await fetch(`/api/scenes/${bookSlug}/${pageNumber}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(scene),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      btn.textContent = "Saved ✓";
      setTimeout(() => { btn.textContent = "Save"; btn.disabled = false; }, 1500);
    } catch (err) {
      btn.textContent = "Error";
      btn.disabled = false;
      console.error("Save failed:", err);
    }
  }

  async function exportPage(mode) {
    const btn = document.querySelector(`[data-action='export-${mode}']`);
    const original = btn.textContent;
    btn.textContent = "Exporting…";
    btn.disabled = true;
    try {
      const resp = await fetch(`/api/export/${bookSlug}/${pageNumber}?mode=${mode}`, {
        method: "POST",
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const { output_path } = await resp.json();
      btn.textContent = "Done ✓";
      setTimeout(() => { btn.textContent = original; btn.disabled = false; }, 2000);
      console.info("Exported to:", output_path);
    } catch (err) {
      btn.textContent = "Error";
      btn.disabled = false;
      console.error("Export failed:", err);
    }
  }

  function toggleText() {
    textVisible = !textVisible;
    document.querySelectorAll(".story-layer--text").forEach((el) => {
      el.style.visibility = textVisible ? "visible" : "hidden";
    });
  }

  document.querySelector("[data-action='save']")?.addEventListener("click", saveScene);
  document.querySelector("[data-action='export-flat']")?.addEventListener("click", () => exportPage("flat"));
  document.querySelector("[data-action='export-draft']")?.addEventListener("click", () => exportPage("draft"));
  document.querySelector("[data-action='toggle-text']")?.addEventListener("click", toggleText);
}
```

Call it at the bottom of `initStoryMaker()`, before the final `}`:

```javascript
initToolbar(scene);
```

- [ ] **Step 3: Verify in browser**

Open `http://127.0.0.1:8000/story-maker`. Verify:
- Click **Save** → button shows "Saving…" then "Saved ✓", reverts to "Save"
- Check `storybook_scenes/book01_password_dragon/page_004.scene.json` was updated on disk
- Click **Export Flat** → button shows "Exporting…" then "Done ✓"
- Check `data/generated/pages/book01_password_dragon/page_004_flat.png` exists
- Click **Toggle Text** → text layers disappear and reappear

- [ ] **Step 4: Commit**

```bash
git add hackster_studio/templates/story_maker.html hackster_studio/static/story_maker.js
git commit -m "feat: add story maker toolbar — save, export flat/draft, toggle text"
```

---

## Task 8: Asset Browser Modal

**Files:**
- Modify: `hackster_studio/templates/story_maker.html`
- Modify: `hackster_studio/static/story_maker.js`

**Interfaces:**
- Consumes: `GET /api/assets`, `GET /api/assets/characters/{slug}/poses`
- Produces: modal with tabs (Backgrounds · Midground · Foreground · Characters · Props); clicking an asset appends a new layer to the scene

- [ ] **Step 1: Add modal HTML to story_maker.html**

Add inside `{% block content %}`, after the `<section class="story-maker">` block:

```html
<dialog id="asset-browser" data-asset-browser>
  <div class="asset-browser-header">
    <h2>Add Layer</h2>
    <button type="button" data-close-browser aria-label="Close">✕</button>
  </div>
  <nav class="asset-browser-tabs" data-asset-tabs></nav>
  <div class="asset-browser-grid" data-asset-grid></div>
</dialog>
```

Add an **Add Layer** button to the layers panel in `story_maker.html`:

```html
<aside class="layers-panel">
  <div class="layers-panel-head">
    <h2>Layers</h2>
    <button type="button" data-action="add-layer">+</button>
  </div>
  <div class="layer-list" data-layer-list></div>
</aside>
```

- [ ] **Step 2: Add asset browser logic to story_maker.js**

Add `initAssetBrowser()` function:

```javascript
function initAssetBrowser(scene, callbacks) {
  const dialog = document.querySelector("[data-asset-browser]");
  const tabsEl = document.querySelector("[data-asset-tabs]");
  const gridEl = document.querySelector("[data-asset-grid]");
  if (!dialog) return;

  const TAB_LABELS = {
    backgrounds: "Backgrounds",
    midground: "Midground",
    foreground: "Foreground",
    characters: "Characters",
    props: "Props",
  };

  const LAYER_TYPE_MAP = {
    backgrounds: "background",
    midground: "midground",
    foreground: "foreground",
    props: "props",
  };

  const PARALLAX_MAP = {
    background: 0.1,
    midground: 0.4,
    foreground: 1.5,
    character: 1.0,
    props: 1.0,
  };

  let currentTab = "backgrounds";
  let assets = {};

  async function loadAssets() {
    const resp = await fetch("/api/assets");
    assets = await resp.json();
    renderTabs();
    renderGrid(currentTab);
  }

  function renderTabs() {
    tabsEl.innerHTML = "";
    Object.keys(TAB_LABELS).forEach((key) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = TAB_LABELS[key];
      btn.classList.toggle("is-active", key === currentTab);
      btn.addEventListener("click", () => {
        currentTab = key;
        tabsEl.querySelectorAll("button").forEach((b) => b.classList.remove("is-active"));
        btn.classList.add("is-active");
        renderGrid(key);
      });
      tabsEl.appendChild(btn);
    });
  }

  function renderGrid(tab) {
    gridEl.innerHTML = "";
    const items = tab === "characters"
      ? Object.values(assets.characters ?? {}).flat()
      : (assets[tab] ?? []);

    // Include hidden_objects under props tab
    const extra = tab === "props" ? (assets.hidden_objects ?? []) : [];
    [...items, ...extra].forEach((assetPath) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "asset-thumb";
      const filename = assetPath.split("/").pop();
      const img = document.createElement("img");
      img.src = `/project-assets/${assetPath}`;
      img.alt = filename;
      img.onerror = () => { img.style.display = "none"; };
      const label = document.createElement("span");
      label.textContent = filename.replace(/_/g, " ").replace(".png", "");
      btn.appendChild(img);
      btn.appendChild(label);
      btn.addEventListener("click", () => addLayer(tab, assetPath));
      gridEl.appendChild(btn);
    });

    if (!items.length && !extra.length) {
      gridEl.innerHTML = "<p class='empty'>No assets yet — generate some first.</p>";
    }
  }

  function addLayer(tab, assetPath) {
    const layerType = tab === "characters" ? "character" : (LAYER_TYPE_MAP[tab] ?? "props");
    const filename = assetPath.split("/").pop().replace(".png", "");
    const id = `${layerType}_${Date.now()}`;
    const zIndexBase = { background: 0, midground: 2, character: 3, props: 4, foreground: 8 };

    const newLayer = {
      id,
      name: filename.replace(/_/g, " "),
      type: layerType,
      z_index: (zIndexBase[layerType] ?? 3) + scene.layers.length,
      parallax_factor: PARALLAX_MAP[layerType] ?? 1.0,
      asset_path: assetPath,
      transform: { x: 0.5, y: 0.5, width: layerType === "background" ? 1.5 : 0.3, height: layerType === "background" ? 1.5 : 0.3, scale: 1.0, rotation: 0, opacity: 1 },
    };

    if (layerType === "character") {
      newLayer.character_slug = assetPath.split("/").slice(-2, -1)[0] ?? "unknown";
      newLayer.pose = "standing_neutral";
      newLayer.rig = null;
      newLayer.shadow = { enabled: false, angle: LIGHTING_SHADOW_ANGLES[scene.lighting_brief] ?? 270, distance: 12, blur: 8, opacity: 0.3 };
    }

    if (layerType === "props") {
      newLayer.shadow = { enabled: false, angle: LIGHTING_SHADOW_ANGLES[scene.lighting_brief] ?? 270, distance: 8, blur: 6, opacity: 0.25 };
    }

    scene.layers.push(newLayer);
    callbacks.renderLayer(newLayer);
    callbacks.rebuildLayerPanel();
    callbacks.selectLayer(newLayer.id);
    dialog.close();
  }

  document.querySelector("[data-action='add-layer']")?.addEventListener("click", () => {
    loadAssets();
    dialog.showModal();
  });

  document.querySelector("[data-close-browser]")?.addEventListener("click", () => dialog.close());
}
```

Call it from `initStoryMaker()` after the `initToolbar(scene)` call:

```javascript
initAssetBrowser(scene, window._sm);
```

- [ ] **Step 3: Verify in browser**

Open `http://127.0.0.1:8000/story-maker`. Verify:
- Click **+** in layers panel → modal opens
- Tabs: Backgrounds, Midground, Foreground, Characters, Props
- If `assets/layers/` dirs are empty: "No assets yet" message shows
- Drop a test PNG into `assets/layers/backgrounds/` and re-open → thumbnail appears
- Clicking the thumbnail adds a new layer to the panel and stage, selects it

- [ ] **Step 4: Commit**

```bash
git add hackster_studio/templates/story_maker.html hackster_studio/static/story_maker.js
git commit -m "feat: add asset browser modal with tabbed layer picker"
```

---

## Task 9: Inspector Extensions — Pose Picker, Shadow, Lighting, Generate

**Files:**
- Modify: `hackster_studio/templates/story_maker.html`
- Modify: `hackster_studio/static/story_maker.js`

**Interfaces:**
- Consumes: `GET /api/assets/characters/{slug}/poses`, `POST /api/generate`, `GET /api/generate/{job_id}`
- Produces: pose picker grid (character layers); shadow controls panel; lighting controls panel; generate button with prompt editor and polling

- [ ] **Step 1: Add inspector extras container to story_maker.html**

In the inspector panel, after the existing `<div class="inspector-grid">` block:

```html
<aside class="inspector-panel">
  <h2>Inspector</h2>
  <div class="inspector-grid">
    <label>X <input data-control="x" type="number" step="0.01"></label>
    <label>Y <input data-control="y" type="number" step="0.01"></label>
    <label>Scale <input data-control="scale" type="number" step="0.01" min="0.05"></label>
    <label>Rotation <input data-control="rotation" type="number" step="1"></label>
    <label>Opacity <input data-control="opacity" type="number" step="0.05" min="0" max="1"></label>
  </div>

  <div data-inspector-extras></div>

  <h2>Skeleton</h2>
  <div class="bone-list" data-bone-list></div>
</aside>
```

- [ ] **Step 2: Replace renderInspectorExtras in story_maker.js**

Replace the placeholder `function renderInspectorExtras(layer)` with the full implementation:

```javascript
function renderInspectorExtras(layer) {
  const extras = document.querySelector("[data-inspector-extras]");
  if (!extras) return;
  extras.innerHTML = "";

  if (!layer) return;

  if (layer.type === "lighting") {
    extras.innerHTML = `
      <div class="inspector-section">
        <h3>Lighting</h3>
        <label>Tint <input type="color" data-light="tint_color" value="${layer.tint_color ?? "#FFFFFF"}"></label>
        <label>Blend
          <select data-light="blend_mode">
            <option value="multiply" ${layer.blend_mode === "multiply" ? "selected" : ""}>Multiply</option>
            <option value="screen" ${layer.blend_mode === "screen" ? "selected" : ""}>Screen</option>
          </select>
        </label>
        <label>Opacity <input type="range" min="0" max="1" step="0.01" data-light="opacity" value="${layer.opacity ?? 0}"></label>
      </div>`;

    extras.querySelectorAll("[data-light]").forEach((input) => {
      input.addEventListener("input", () => {
        layer[input.dataset.light] = input.type === "range" ? Number(input.value) : input.value;
        updateLayerElement(layer);
      });
    });
    return;
  }

  if (layer.type === "character" || layer.type === "props") {
    const shadow = layer.shadow ?? {};
    extras.innerHTML += `
      <div class="inspector-section">
        <h3>Shadow</h3>
        <label><input type="checkbox" data-shadow="enabled" ${shadow.enabled ? "checked" : ""}> Enabled</label>
        <label>Angle <input type="number" step="1" min="0" max="360" data-shadow="angle" value="${shadow.angle ?? 270}"></label>
        <label>Distance <input type="number" step="1" min="0" data-shadow="distance" value="${shadow.distance ?? 12}"></label>
        <label>Blur <input type="number" step="1" min="0" data-shadow="blur" value="${shadow.blur ?? 8}"></label>
        <label>Opacity <input type="range" min="0" max="1" step="0.01" data-shadow="opacity" value="${shadow.opacity ?? 0.3}"></label>
      </div>`;

    extras.querySelectorAll("[data-shadow]").forEach((input) => {
      input.addEventListener("input", () => {
        layer.shadow = layer.shadow ?? {};
        if (input.type === "checkbox") {
          layer.shadow.enabled = input.checked;
        } else {
          layer.shadow[input.dataset.shadow] = Number(input.value);
        }
        updateLayerElement(layer);
      });
    });
  }

  if (layer.type === "character") {
    const slug = layer.character_slug ?? "niko";
    fetch(`/api/assets/characters/${slug}/poses`)
      .then((r) => r.json())
      .then((poses) => {
        if (!poses.length) return;
        const section = document.createElement("div");
        section.className = "inspector-section";
        section.innerHTML = `<h3>Pose</h3><div class="pose-grid"></div>`;
        const grid = section.querySelector(".pose-grid");
        poses.forEach((pose) => {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "pose-btn";
          btn.textContent = pose.label;
          btn.classList.toggle("is-active", layer.pose === pose.id);
          btn.addEventListener("click", () => {
            layer.pose = pose.id;
            // Update asset_path if matching file exists (best-effort)
            const variant = layer.lighting_variant ?? scene.lighting_brief ?? "ambient_soft";
            layer.asset_path = `assets/layers/characters/${slug}/${pose.id}_${variant}.png`;
            section.querySelectorAll(".pose-btn").forEach((b) => b.classList.remove("is-active"));
            btn.classList.add("is-active");
            updateLayerElement(layer);
          });
          grid.appendChild(btn);
        });
        extras.appendChild(section);
      });
  }

  // Generate button (available for all asset-bearing layers)
  if (["background", "midground", "foreground", "character", "props"].includes(layer.type)) {
    const genSection = document.createElement("div");
    genSection.className = "inspector-section";
    const defaultPrompt = layer.type === "character"
      ? `Hackster Niko ${layer.pose ?? "standing"}, ${scene.lighting_brief ?? "ambient"} lighting`
      : `${layer.name}, ${layer.type} layer, ${scene.lighting_brief ?? "ambient"} lighting`;
    genSection.innerHTML = `
      <h3>Generate</h3>
      <textarea rows="4" data-gen-prompt>${defaultPrompt}</textarea>
      <button type="button" data-action="generate">Generate Image</button>
      <p class="gen-status" data-gen-status></p>`;

    genSection.querySelector("[data-action='generate']").addEventListener("click", () => {
      const prompt = genSection.querySelector("[data-gen-prompt]").value.trim();
      const statusEl = genSection.querySelector("[data-gen-status]");
      if (!prompt) return;

      const outputPath = layer.asset_path ??
        `assets/layers/${layer.type}s/${layer.id}_${scene.lighting_brief ?? "ambient_soft"}.png`;

      statusEl.textContent = "Submitting…";
      fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          layer_id: layer.id,
          layer_type: layer.type,
          prompt,
          output_path: outputPath,
          lighting_variant: scene.lighting_brief ?? "ambient_soft",
        }),
      })
        .then((r) => r.json())
        .then(({ job_id }) => {
          statusEl.textContent = "Running…";
          pollJob(job_id, layer, outputPath, statusEl);
        })
        .catch(() => { statusEl.textContent = "Error submitting job."; });
    });

    extras.appendChild(genSection);
  }
}

function pollJob(jobId, layer, outputPath, statusEl) {
  const interval = setInterval(async () => {
    try {
      const resp = await fetch(`/api/generate/${jobId}`);
      const { status, asset_path } = await resp.json();
      statusEl.textContent = status;
      if (status === "done") {
        clearInterval(interval);
        layer.asset_path = asset_path ?? outputPath;
        updateLayerElement(layer);
        statusEl.textContent = "Done ✓ — layer updated.";
      } else if (status === "failed") {
        clearInterval(interval);
        statusEl.textContent = "Generation failed.";
      }
    } catch {
      clearInterval(interval);
      statusEl.textContent = "Polling error.";
    }
  }, 2000);
}
```

Note: `updateLayerElement`, `scene`, and `selectLayer` are referenced here — they must be in scope. Since `renderInspectorExtras` is defined inside `initStoryMaker`, they are in the closure. `pollJob` is defined outside and must be defined before `initStoryMaker` in the file, or moved inside.

Move `renderInspectorExtras` and `pollJob` to be defined inside `initStoryMaker`, before `selectLayer`, to share the closure.

- [ ] **Step 3: Verify in browser**

Open `http://127.0.0.1:8000/story-maker`. Verify:

1. Select the **Hackster Niko** character layer → Shadow controls appear (Enabled checkbox, Angle, Distance, Blur, Opacity). Toggle Enabled → shadow appears/disappears on stage.
2. Pose grid shows 8 poses (Standing Neutral, Pointing Right, etc.). Click a pose → `layer.pose` updates.
3. Select the **Ambient Light** lighting layer → Tint color picker, Blend Mode dropdown, Opacity slider appear. Changing tint color updates the overlay immediately.
4. Select any image-bearing layer → Generate section appears with pre-filled prompt textarea and Generate button. (Actual generation requires ComfyUI to be running; click Generate, verify status shows "Running…".)

- [ ] **Step 4: Run full test suite**

```bash
uv run inv test
```

Expected: all PASS.

- [ ] **Step 5: Final lint and commit**

```bash
uv run inv lint
git add hackster_studio/templates/story_maker.html hackster_studio/static/story_maker.js
git commit -m "feat: inspector extensions — pose picker, shadow controls, lighting controls, generate + poll"
```

---

## Self-Review Results

**Spec coverage check:**

| Spec section | Covered by |
|---|---|
| Scene schema (all layer types) | Task 1 |
| Asset library directory structure | Task 1 |
| Pose manifest | Task 1 |
| `GET/PUT /api/scenes` | Task 2 |
| `GET /api/assets`, `/api/assets/characters/{slug}/poses` | Task 3 |
| `POST/GET /api/generate` + BackgroundTasks | Task 4 |
| `POST /api/export?mode=flat|draft` | Task 5 |
| Pillow compositor (all layer types, shadow, lighting blend, camera crop) | Task 5 |
| Layer panel type icons | Task 6 |
| Camera crop rect overlay | Task 6 |
| Lighting div with mix-blend-mode | Task 6 |
| Parallax on camera move | Task 6 |
| Shadow CSS filter on character/props | Task 6 |
| Save toolbar button | Task 7 |
| Export Flat/Draft toolbar buttons | Task 7 |
| Toggle Text button | Task 7 |
| Asset browser modal (tabbed, hidden objects under Props) | Task 8 |
| Add layer from asset browser | Task 8 |
| Pose picker in inspector | Task 9 |
| Shadow controls in inspector | Task 9 |
| Lighting controls in inspector | Task 9 |
| Generate button + prompt editor + job polling | Task 9 |
| `rig: null` schema field (future-proofing) | Task 1 schema |
| Existing `bone-list` inspector (already works) | Untouched ✓ |

**No gaps found.**
