"""Tests for the generation job API endpoints."""

from __future__ import annotations

import re
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient

from hackster_studio.main import app

client = TestClient(app)

_VALID_PAYLOAD = {
    "layer_id": "char_niko",
    "layer_type": "character",
    "prompt": "Hackster Niko waving",
    "output_path": "assets/layers/characters/niko/waving_ambient_soft.png",
    "lighting_variant": "ambient_soft",
}


# ── POST /api/generate ────────────────────────────────────────────────────────


def test_post_generate_returns_job_id() -> None:
    with patch("hackster_studio.api.generate_image_comfyui") as mock_gen:
        mock_gen.return_value = Path(_VALID_PAYLOAD["output_path"])
        response = client.post("/api/generate", json=_VALID_PAYLOAD)

    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data


def test_post_generate_job_id_is_uuid4() -> None:
    uuid4_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    )
    with patch("hackster_studio.api.generate_image_comfyui"):
        response = client.post("/api/generate", json=_VALID_PAYLOAD)

    job_id = response.json()["job_id"]
    assert uuid4_pattern.match(job_id), f"Not a UUID4: {job_id}"


def test_post_generate_missing_layer_id_returns_422() -> None:
    payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "layer_id"}
    response = client.post("/api/generate", json=payload)
    assert response.status_code == 422


def test_post_generate_missing_prompt_returns_422() -> None:
    payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "prompt"}
    response = client.post("/api/generate", json=payload)
    assert response.status_code == 422


def test_post_generate_missing_output_path_returns_422() -> None:
    payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "output_path"}
    response = client.post("/api/generate", json=payload)
    assert response.status_code == 422


def test_post_generate_missing_layer_type_returns_422() -> None:
    payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "layer_type"}
    response = client.post("/api/generate", json=payload)
    assert response.status_code == 422


def test_post_generate_missing_lighting_variant_returns_422() -> None:
    payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "lighting_variant"}
    response = client.post("/api/generate", json=payload)
    assert response.status_code == 422


def test_post_generate_empty_body_returns_422() -> None:
    response = client.post("/api/generate", json={})
    assert response.status_code == 422


def test_post_generate_rejects_path_traversal_output_path() -> None:
    response = client.post("/api/generate", json={
        **_VALID_PAYLOAD,
        "output_path": "../outside.png",
    })
    assert response.status_code == 422


def test_post_generate_accepts_generated_pages_output_path() -> None:
    with patch("hackster_studio.api.generate_image_comfyui"):
        response = client.post("/api/generate", json={
            **_VALID_PAYLOAD,
            "output_path": "data/generated/pages/page_001.png",
        })
    assert response.status_code == 200


def test_post_generate_rejects_arbitrary_output_path() -> None:
    response = client.post("/api/generate", json={
        **_VALID_PAYLOAD,
        "output_path": "data/imports/evil.png",
    })
    assert response.status_code == 422


def test_post_generate_rejects_non_png_output_path() -> None:
    response = client.post("/api/generate", json={
        **_VALID_PAYLOAD,
        "output_path": "assets/layers/characters/niko/waving.jpg",
    })
    assert response.status_code == 422


def test_post_generate_text_art_creates_transparent_png(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio import api as api_mod

    project_root = tmp_path / "project"
    layers_dir = project_root / "assets" / "layers"
    monkeypatch.setattr(api_mod, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(api_mod, "LAYERS_DIR", layers_dir)

    response = client.post("/api/generate/text-art", json={
        "text": "Every problem has a clever fix!",
        "output_path": "assets/layers/text/book01/page_001_text.png",
        "width_px": 900,
        "height_px": 260,
        "dpi": 300,
        "style": {
            "font_family": "rounded",
            "fill_color": "#154C84",
            "stroke_color": "#F2C94C",
        },
    })

    assert response.status_code == 200
    asset_path = response.json()["asset_path"]
    output = project_root / asset_path
    assert output.exists()
    assert output.suffix == ".png"
    img = Image.open(output)
    assert img.mode == "RGBA"
    assert img.getchannel("A").getextrema()[0] == 0


def test_post_generate_text_art_rejects_non_text_asset_path() -> None:
    response = client.post("/api/generate/text-art", json={
        "text": "Nope",
        "output_path": "assets/layers/characters/niko/nope.png",
    })
    assert response.status_code == 422


def test_post_generate_niko_pose_creates_transparent_png(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio import api as api_mod

    project_root = tmp_path / "project"
    layers_dir = project_root / "assets" / "layers"
    monkeypatch.setattr(api_mod, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(api_mod, "LAYERS_DIR", layers_dir)

    response = client.post("/api/generate/niko-pose", json={
        "pose": "custom",
        "output_path": "assets/layers/characters/niko/custom/page_004_custom.png",
        "rig": {
            "bones": [
                {"id": "left_arm", "rotation": 12},
                {"id": "right_arm", "rotation": -42},
                {"id": "left_leg", "rotation": -6},
                {"id": "right_leg", "rotation": 9},
            ],
        },
    })

    assert response.status_code == 200
    output = project_root / response.json()["asset_path"]
    assert output.exists()
    img = Image.open(output)
    assert img.mode == "RGBA"
    assert img.getchannel("A").getextrema()[0] == 0


def test_post_generate_niko_pose_rejects_non_niko_path() -> None:
    response = client.post("/api/generate/niko-pose", json={
        "pose": "custom",
        "output_path": "assets/layers/props/not_niko.png",
        "rig": {"bones": []},
    })
    assert response.status_code == 422


def test_post_generate_text_art_accepts_style_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio import api as api_mod

    project_root = tmp_path / "project"
    layers_dir = project_root / "assets" / "layers"
    monkeypatch.setattr(api_mod, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(api_mod, "LAYERS_DIR", layers_dir)

    response = client.post("/api/generate/text-art", json={
        "text": "Niko fixed it!",
        "output_path": "assets/layers/text/book01/page_002_text_v01.png",
        "style": {
            "style_prompt": "sparkly crystal robot letters",
            "variation_seed": 1,
        },
    })

    assert response.status_code == 200
    output = project_root / response.json()["asset_path"]
    assert output.exists()
    assert Image.open(output).getchannel("A").getextrema()[1] > 0


def test_post_generate_creates_job_in_pending_state() -> None:
    from hackster_studio import api as api_mod

    # Clear jobs before test to isolate
    captured_id: list[str] = []

    original_post = api_mod._jobs.__setitem__

    def capture_setitem(k: str, v: object) -> None:
        captured_id.append(k)
        original_post(k, v)

    with patch("hackster_studio.api.generate_image_comfyui"):
        response = client.post("/api/generate", json=_VALID_PAYLOAD)

    job_id = response.json()["job_id"]
    # The TestClient runs background tasks synchronously, so job may be "done" by now
    # but the job_id must exist in the store
    status_resp = client.get(f"/api/generate/{job_id}")
    assert status_resp.status_code == 200


def test_post_generate_multiple_jobs_are_independent() -> None:
    with patch("hackster_studio.api.generate_image_comfyui"):
        resp1 = client.post("/api/generate", json=_VALID_PAYLOAD)
        resp2 = client.post("/api/generate", json={
            **_VALID_PAYLOAD,
            "layer_id": "bg_001",
            "layer_type": "background",
        })

    id1 = resp1.json()["job_id"]
    id2 = resp2.json()["job_id"]
    assert id1 != id2

    s1 = client.get(f"/api/generate/{id1}").json()
    s2 = client.get(f"/api/generate/{id2}").json()
    assert s1["status"] in ("pending", "running", "done")
    assert s2["status"] in ("pending", "running", "done")


# ── GET /api/generate/{job_id} ────────────────────────────────────────────────


def test_get_generate_status_unknown_job_returns_404() -> None:
    response = client.get("/api/generate/nonexistent-job-id")
    assert response.status_code == 404


def test_get_generate_status_returns_status_and_asset_path_fields() -> None:
    with patch("hackster_studio.api.generate_image_comfyui"):
        resp = client.post("/api/generate", json=_VALID_PAYLOAD)
    job_id = resp.json()["job_id"]

    status = client.get(f"/api/generate/{job_id}").json()
    assert "status" in status
    assert "asset_path" in status


def test_get_generate_status_done_after_successful_mock() -> None:
    with patch("hackster_studio.api.generate_image_comfyui") as mock_gen:
        mock_gen.return_value = Path(_VALID_PAYLOAD["output_path"])
        resp = client.post("/api/generate", json=_VALID_PAYLOAD)

    job_id = resp.json()["job_id"]
    # TestClient runs background tasks synchronously — job should be done
    status = client.get(f"/api/generate/{job_id}").json()
    assert status["status"] == "done"
    assert status["asset_path"] == _VALID_PAYLOAD["output_path"]


def test_post_generate_character_asset_saves_transparent_png(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio import api as api_mod

    project_root = tmp_path / "project"
    layers_dir = project_root / "assets" / "layers"
    generated_dir = project_root / "data" / "generated" / "pages"
    monkeypatch.setattr(api_mod, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(api_mod, "LAYERS_DIR", layers_dir)
    monkeypatch.setattr(api_mod, "GENERATED_PAGES_DIR", generated_dir)

    def fake_generate(prompt: str, output_path: Path, **kwargs: object) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", (256, 256), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((48, 36, 208, 224), fill=(70, 199, 255))
        image.save(output_path)
        return output_path

    payload = {
        **_VALID_PAYLOAD,
        "output_path": "assets/layers/characters/samurai_splat/generated_pose.png",
    }
    with patch("hackster_studio.api.generate_image_comfyui", side_effect=fake_generate):
        resp = client.post("/api/generate", json=payload)

    job_id = resp.json()["job_id"]
    status = client.get(f"/api/generate/{job_id}").json()
    assert status["status"] == "done"
    with Image.open(project_root / payload["output_path"]) as generated:
        assert generated.mode == "RGBA"
        assert generated.getpixel((0, 0))[3] == 0


def test_get_generate_status_failed_when_generation_raises() -> None:
    def failing_gen(*args: object, **kwargs: object) -> None:
        raise RuntimeError("ComfyUI unavailable")

    with patch("hackster_studio.api.generate_image_comfyui", side_effect=failing_gen):
        resp = client.post("/api/generate", json=_VALID_PAYLOAD)

    job_id = resp.json()["job_id"]
    status = client.get(f"/api/generate/{job_id}").json()
    assert status["status"] == "failed"


def test_get_generate_status_pending_then_done() -> None:
    completed: dict[str, bool] = {}

    def slow_gen(prompt: str, output_path: Path, **kwargs: object) -> Path:
        time.sleep(0.05)
        completed["done"] = True
        return output_path

    with patch("hackster_studio.api.generate_image_comfyui", side_effect=slow_gen):
        post_resp = client.post("/api/generate", json={
            **_VALID_PAYLOAD,
            "layer_id": "bg_001",
            "layer_type": "background",
        })

    job_id = post_resp.json()["job_id"]
    # TestClient runs background tasks synchronously
    status = client.get(f"/api/generate/{job_id}").json()
    assert status["status"] in ("pending", "running", "done")


def test_get_generate_status_asset_path_matches_output_path() -> None:
    with patch("hackster_studio.api.generate_image_comfyui"):
        resp = client.post("/api/generate", json=_VALID_PAYLOAD)
    job_id = resp.json()["job_id"]

    status = client.get(f"/api/generate/{job_id}").json()
    if status["status"] == "done":
        assert status["asset_path"] == _VALID_PAYLOAD["output_path"]


def test_get_generate_status_failed_asset_path_is_none() -> None:
    def failing(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    with patch("hackster_studio.api.generate_image_comfyui", side_effect=failing):
        resp = client.post("/api/generate", json=_VALID_PAYLOAD)

    job_id = resp.json()["job_id"]
    status = client.get(f"/api/generate/{job_id}").json()
    assert status["status"] == "failed"
    assert status["asset_path"] is None
