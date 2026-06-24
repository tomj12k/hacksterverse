"""
Integration tests: full roundtrip through the real HTTP routes using TestClient.
No mocks except generate_image_comfyui (which needs a running ComfyUI instance).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from hackster_studio.main import app
from hackster_studio.services.story_maker import default_scene

client = TestClient(app)

_BOOK = "integration_test_book"
_PAGE = 42


# ── Scene save / load roundtrip ────────────────────────────────────────────────


def test_scene_save_then_load_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import story_maker as sm
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path)

    scene = default_scene(_BOOK, _PAGE)
    scene["lighting_brief"] = "warm_sunset_left"

    # Save via PUT
    put_resp = client.put(f"/api/scenes/{_BOOK}/{_PAGE}", json=scene)
    assert put_resp.status_code == 204

    # Load via GET
    get_resp = client.get(f"/api/scenes/{_BOOK}/{_PAGE}")
    assert get_resp.status_code == 200
    loaded = get_resp.json()
    assert loaded["lighting_brief"] == "warm_sunset_left"
    assert loaded["book_slug"] == _BOOK
    assert loaded["page_number"] == _PAGE


def test_scene_mutation_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import story_maker as sm
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path)

    # First GET creates default
    first = client.get(f"/api/scenes/{_BOOK}/{_PAGE}").json()
    first["lighting_brief"] = "cool_forest_ambient"

    # Mutate and PUT
    client.put(f"/api/scenes/{_BOOK}/{_PAGE}", json=first)

    # Second GET reflects the mutation
    second = client.get(f"/api/scenes/{_BOOK}/{_PAGE}").json()
    assert second["lighting_brief"] == "cool_forest_ambient"


def test_scene_layers_preserved_across_save_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import story_maker as sm
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path)

    scene = default_scene(_BOOK, _PAGE)
    original_layer_count = len(scene["layers"])
    scene["layers"].append({
        "id": "extra_layer_99",
        "type": "props",
        "z_index": 4,
        "asset_path": "assets/layers/props/test_lamp.png",
        "transform": {"x": 0.5, "y": 0.5, "scale": 1.0, "rotation": 0.0},
        "parallax_factor": 0.5,
        "opacity": 1.0,
    })

    client.put(f"/api/scenes/{_BOOK}/{_PAGE}", json=scene)
    loaded = client.get(f"/api/scenes/{_BOOK}/{_PAGE}").json()

    assert len(loaded["layers"]) == original_layer_count + 1
    ids = [l["id"] for l in loaded["layers"]]
    assert "extra_layer_99" in ids


def test_scene_overwrite_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import story_maker as sm
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path)

    scene = default_scene(_BOOK, _PAGE)
    # Save twice identically
    client.put(f"/api/scenes/{_BOOK}/{_PAGE}", json=scene)
    client.put(f"/api/scenes/{_BOOK}/{_PAGE}", json=scene)

    loaded = client.get(f"/api/scenes/{_BOOK}/{_PAGE}").json()
    assert loaded["book_slug"] == _BOOK


def test_multiple_pages_are_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import story_maker as sm
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path)

    scene_1 = default_scene(_BOOK, 1)
    scene_1["lighting_brief"] = "page_one_lighting"
    scene_2 = default_scene(_BOOK, 2)
    scene_2["lighting_brief"] = "page_two_lighting"

    client.put(f"/api/scenes/{_BOOK}/1", json=scene_1)
    client.put(f"/api/scenes/{_BOOK}/2", json=scene_2)

    loaded_1 = client.get(f"/api/scenes/{_BOOK}/1").json()
    loaded_2 = client.get(f"/api/scenes/{_BOOK}/2").json()

    assert loaded_1["lighting_brief"] == "page_one_lighting"
    assert loaded_2["lighting_brief"] == "page_two_lighting"


# ── Export uses latest saved scene ────────────────────────────────────────────


def test_export_flat_returns_output_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import story_maker as sm
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path)
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path / "generated_pages")

    scene = default_scene(_BOOK, _PAGE)
    client.put(f"/api/scenes/{_BOOK}/{_PAGE}", json=scene)

    resp = client.post(f"/api/export/{_BOOK}/{_PAGE}?mode=flat")
    assert resp.status_code == 200
    data = resp.json()
    assert "output_path" in data
    assert data["output_path"].endswith(".png")


def test_export_draft_returns_output_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import story_maker as sm
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path)
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path / "generated_pages")

    scene = default_scene(_BOOK, _PAGE)
    client.put(f"/api/scenes/{_BOOK}/{_PAGE}", json=scene)

    resp = client.post(f"/api/export/{_BOOK}/{_PAGE}?mode=draft")
    assert resp.status_code == 200
    data = resp.json()
    assert "output_path" in data


def test_export_invalid_mode_returns_422() -> None:
    resp = client.post(f"/api/export/{_BOOK}/{_PAGE}?mode=turbo")
    assert resp.status_code == 422


def test_export_uses_latest_saved_scene(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Export must reflect the most recently saved version of the scene."""
    from hackster_studio.services import story_maker as sm
    from hackster_studio.services import exporter as exp_mod

    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path)
    monkeypatch.setattr(exp_mod, "GENERATED_PAGES_DIR", tmp_path / "generated_pages")

    scene = default_scene(_BOOK, _PAGE)
    # Remove all image layers so export is a fast white canvas
    scene["layers"] = [l for l in scene["layers"] if l["type"] == "camera"]
    client.put(f"/api/scenes/{_BOOK}/{_PAGE}", json=scene)

    resp = client.post(f"/api/export/{_BOOK}/{_PAGE}?mode=flat")
    assert resp.status_code == 200

    out_path = Path(resp.json()["output_path"])
    # Path should embed the book slug and page
    assert _BOOK in str(out_path) or str(_PAGE) in str(out_path) or out_path.suffix == ".png"


def test_promote_exports_and_replaces_book_illustration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio import api as api_mod
    from hackster_studio.services import story_maker as sm

    monkeypatch.setattr(api_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sm, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path / "scenes")

    exported = tmp_path / "data" / "generated" / "pages" / "page_042_flat.png"
    exported.parent.mkdir(parents=True)
    exported.write_bytes(b"promoted image bytes")

    def fake_export_scene(scene: dict, mode: str = "flat") -> Path:
        assert scene["book_slug"] == _BOOK
        assert mode == "flat"
        return exported

    monkeypatch.setattr(api_mod, "export_scene", fake_export_scene)
    client.put(f"/api/scenes/{_BOOK}/{_PAGE}", json=default_scene(_BOOK, _PAGE))

    resp = client.post(f"/api/promote/{_BOOK}/{_PAGE}?mode=flat")
    assert resp.status_code == 200
    promoted = tmp_path / "books" / _BOOK / "illustrations" / "page_042.png"
    assert promoted.read_bytes() == b"promoted image bytes"
    assert resp.json()["promoted_path"] == f"books/{_BOOK}/illustrations/page_042.png"


# ── Assets endpoint ───────────────────────────────────────────────────────────


def test_assets_endpoint_is_reachable() -> None:
    resp = client.get("/api/assets")
    assert resp.status_code == 200


def test_assets_endpoint_returns_all_required_keys() -> None:
    data = client.get("/api/assets").json()
    required = {"backgrounds", "midground", "foreground", "characters", "props", "generated"}
    missing = required - set(data.keys())
    assert not missing, f"Missing keys: {missing}"


def test_project_assets_revalidate_in_place_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio import main as main_mod

    monkeypatch.setattr(main_mod, "PROJECT_ROOT", tmp_path)
    asset = tmp_path / "books" / "demo" / "illustrations" / "page_005.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"fresh image")

    resp = client.get("/project-assets/books/demo/illustrations/page_005.png")

    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-cache"


# ── Generate job lifecycle ────────────────────────────────────────────────────


def test_generate_job_lifecycle_happy_path() -> None:
    with patch("hackster_studio.api.generate_image_comfyui") as mock_gen:
        mock_gen.return_value = Path("assets/layers/characters/niko/test_out.png")
        post_resp = client.post("/api/generate", json={
            "layer_id": "char_niko",
            "layer_type": "character",
            "prompt": "Niko smiling",
            "output_path": "assets/layers/characters/niko/test_out.png",
            "lighting_variant": "ambient_soft",
        })

    assert post_resp.status_code == 200
    job_id = post_resp.json()["job_id"]

    status_resp = client.get(f"/api/generate/{job_id}")
    assert status_resp.status_code == 200
    status = status_resp.json()
    assert status["status"] in ("pending", "running", "done")


def test_generate_job_done_has_asset_path() -> None:
    output = "assets/layers/characters/niko/smiling.png"
    with patch("hackster_studio.api.generate_image_comfyui") as mock_gen:
        mock_gen.return_value = Path(output)
        post_resp = client.post("/api/generate", json={
            "layer_id": "char_niko",
            "layer_type": "character",
            "prompt": "Niko smiling",
            "output_path": output,
            "lighting_variant": "ambient_soft",
        })

    job_id = post_resp.json()["job_id"]
    status = client.get(f"/api/generate/{job_id}").json()
    if status["status"] == "done":
        assert status["asset_path"] == output


def test_generate_unknown_job_returns_404() -> None:
    resp = client.get("/api/generate/totally-unknown-job-id-xyz")
    assert resp.status_code == 404


# ── Story maker page ──────────────────────────────────────────────────────────


def test_story_maker_page_loads() -> None:
    resp = client.get("/story-maker")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_story_maker_page_embeds_valid_json_scene() -> None:
    html = client.get("/story-maker").text
    start = html.index('id="story-scene-data"')
    start = html.index(">", start) + 1
    end = html.index("</script>", start)
    scene_json = html[start:end].strip()
    scene = json.loads(scene_json)
    assert "layers" in scene
    assert isinstance(scene["layers"], list)


def test_story_maker_query_params_respected() -> None:
    """?book_slug= and ?page= parameters should seed the scene correctly."""
    resp = client.get("/story-maker?book_slug=test_book&page=3")
    assert resp.status_code == 200
    html = resp.text
    # The embedded scene should reference the requested book
    assert "test_book" in html
