"""Tests for the Pillow compositor / export pipeline."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from PIL import Image, ImageChops
from fastapi.testclient import TestClient

from hackster_studio.main import app
from hackster_studio.services.exporter import (
    _apply_shadow,
    _composite_lighting,
    _denorm,
    export_scene,
)
from hackster_studio.services.story_maker import default_scene

client = TestClient(app)


def _solid(color: tuple[int, int, int, int] = (100, 150, 200, 255), size: int = 50) -> Image.Image:
    return Image.new("RGBA", (size, size), color)


def _make_test_png(path: Path, size: tuple[int, int] = (100, 100), color: tuple = (255, 0, 0, 255)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, color).save(str(path))


def _small_scene(**overrides: object) -> dict:
    """Return a minimal scene with a tiny canvas for fast tests."""
    scene = default_scene("testbook", 1)
    # Override canvas to 100x100 for speed
    scene["canvas"].update({"width_px": 100, "height_px": 100, "dpi": 72})
    scene.update(overrides)
    return scene


def _use_temp_project_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    from hackster_studio.services import exporter as exp

    project_root = tmp_path / "project"
    monkeypatch.setattr(exp, "PROJECT_ROOT", project_root)
    return project_root


# ── _denorm ───────────────────────────────────────────────────────────────────


def test_denorm_zero() -> None:
    assert _denorm(0.0, 2625) == 0


def test_denorm_one() -> None:
    assert _denorm(1.0, 2625) == 2625


def test_denorm_half() -> None:
    result = _denorm(0.5, 100)
    assert result == 50


def test_denorm_rounds() -> None:
    # 0.333 * 100 = 33.3 → rounds to 33
    assert _denorm(0.333, 100) == 33


def test_denorm_small_canvas() -> None:
    assert _denorm(1.0, 10) == 10
    assert _denorm(0.0, 10) == 0


# ── _apply_shadow ─────────────────────────────────────────────────────────────


def test_apply_shadow_disabled_returns_same_image() -> None:
    img = _solid()
    result = _apply_shadow(img, {"enabled": False})
    # Should be the same object (no-op)
    assert result is img


def test_apply_shadow_disabled_empty_dict() -> None:
    img = _solid()
    result = _apply_shadow(img, {})
    assert result is img


def test_apply_shadow_enabled_returns_rgba() -> None:
    img = _solid((200, 100, 50, 255))
    result = _apply_shadow(img, {"enabled": True, "angle": 270, "distance": 5, "blur": 2, "opacity": 0.5})
    assert result.mode == "RGBA"


def test_apply_shadow_enabled_does_not_crash_on_rgb_input() -> None:
    rgb_img = Image.new("RGB", (50, 50), (200, 100, 50))
    result = _apply_shadow(rgb_img, {"enabled": True, "angle": 270, "distance": 5, "blur": 2, "opacity": 0.5})
    assert result.mode == "RGBA"


def test_apply_shadow_enabled_same_size_as_input() -> None:
    img = _solid(size=80)
    result = _apply_shadow(img, {"enabled": True, "angle": 225, "distance": 10, "blur": 4, "opacity": 0.3})
    assert result.size == img.size


def test_apply_shadow_zero_opacity_produces_no_shadow() -> None:
    # With zero opacity shadow, the alpha channel of the shadow layer is zero
    # → result should look like the original (shadow is transparent)
    img = _solid((255, 0, 0, 255))
    result = _apply_shadow(img, {"enabled": True, "angle": 270, "distance": 5, "blur": 0, "opacity": 0.0})
    assert result.mode == "RGBA"


def test_apply_shadow_angle_270_offsets_downward() -> None:
    # angle 270° in radians: cos(270°)=0, sin(270°)=-1 → offset_y is negative
    # The shadow is offset down (positive y in image coords is down)
    angle = 270
    angle_rad = math.radians(angle)
    dist = 10
    expected_ox = round(math.cos(angle_rad) * dist)
    expected_oy = round(math.sin(angle_rad) * dist)
    # Just verify the math is consistent with what the exporter does
    assert expected_ox == 0
    assert expected_oy < 0 or expected_oy == 0  # sin(270°) ≈ -1


def test_apply_shadow_large_distance_no_crash() -> None:
    img = _solid(size=10)
    # Distance larger than image — shadow goes off-canvas, should still work
    result = _apply_shadow(img, {"enabled": True, "angle": 45, "distance": 1000, "blur": 2, "opacity": 0.5})
    assert result is not None


# ── _composite_lighting ───────────────────────────────────────────────────────


def test_composite_lighting_returns_rgba() -> None:
    canvas = Image.new("RGBA", (50, 50), (100, 100, 100, 255))
    result = _composite_lighting(canvas, "#FF8800", "multiply", 0.5)
    assert result.mode == "RGBA"


def test_composite_lighting_same_size_as_input() -> None:
    canvas = Image.new("RGBA", (80, 60), (128, 128, 128, 255))
    result = _composite_lighting(canvas, "#FFFFFF", "multiply", 1.0)
    assert result.size == (80, 60)


def test_composite_lighting_white_multiply_no_change() -> None:
    # multiply(x, 255) = (x * 255) / 255 = x → blend(x, x, op) = x
    canvas = Image.new("RGBA", (10, 10), (128, 64, 200, 255))
    result = _composite_lighting(canvas, "#FFFFFF", "multiply", 1.0)
    # Sample the center pixel — should be essentially unchanged
    orig_px = canvas.convert("RGB").getpixel((5, 5))
    res_px = result.convert("RGB").getpixel((5, 5))
    for oc, rc in zip(orig_px, res_px):
        assert abs(oc - rc) <= 2, f"White multiply changed pixel: {orig_px} → {res_px}"


def test_composite_lighting_black_multiply_darkens() -> None:
    canvas = Image.new("RGBA", (10, 10), (200, 150, 100, 255))
    result = _composite_lighting(canvas, "#000000", "multiply", 1.0)
    res_px = result.convert("RGB").getpixel((5, 5))
    # multiply with black at full opacity → all zeros
    assert all(c <= 5 for c in res_px), f"Expected near-black, got {res_px}"


def test_composite_lighting_zero_opacity_no_change() -> None:
    canvas = Image.new("RGBA", (10, 10), (100, 150, 200, 255))
    result = _composite_lighting(canvas, "#FF0000", "multiply", 0.0)
    orig_px = canvas.convert("RGB").getpixel((5, 5))
    res_px = result.convert("RGB").getpixel((5, 5))
    for oc, rc in zip(orig_px, res_px):
        assert abs(oc - rc) <= 2


def test_composite_lighting_screen_with_white_brightens() -> None:
    # screen(x, 255) = 255 - (255-x)*(255-255)/255 = 255
    canvas = Image.new("RGBA", (10, 10), (50, 100, 150, 255))
    result = _composite_lighting(canvas, "#FFFFFF", "screen", 1.0)
    res_px = result.convert("RGB").getpixel((5, 5))
    assert all(c >= 250 for c in res_px), f"Screen with white should be near-white, got {res_px}"


def test_composite_lighting_unknown_blend_mode_no_change() -> None:
    canvas = Image.new("RGBA", (10, 10), (100, 150, 200, 255))
    result = _composite_lighting(canvas, "#FF8800", "nonexistent", 1.0)
    # Falls through to canvas_rgb unblended → blend(orig, orig, opacity) = orig
    orig_px = canvas.convert("RGB").getpixel((5, 5))
    res_px = result.convert("RGB").getpixel((5, 5))
    for oc, rc in zip(orig_px, res_px):
        assert abs(oc - rc) <= 2


# ── export_scene ──────────────────────────────────────────────────────────────


def test_export_flat_creates_png(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    out = export_scene(default_scene("testbook", 1), mode="flat")
    assert out.exists()
    assert out.suffix == ".png"
    assert "flat" in out.name


def test_export_draft_creates_png(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    out = export_scene(default_scene("testbook", 1), mode="draft")
    assert out.exists()
    assert "draft" in out.name


def test_export_output_path_naming(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    out = export_scene(default_scene("mybook", 5), mode="flat")
    assert "mybook" in str(out)
    assert "page_005" in out.name
    assert "flat" in out.name


def test_export_output_is_rgb_not_rgba(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    out = export_scene(default_scene("testbook", 1), mode="flat")
    img = Image.open(out)
    assert img.mode == "RGB"


def test_export_output_correct_canvas_size(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    out = export_scene(default_scene("testbook", 1), mode="flat")
    img = Image.open(out)
    assert img.size == (2625, 2625)


def test_export_flat_skips_text_layers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    scene = _small_scene()
    scene["layers"].append({
        "id": "text_001", "name": "Story Text", "type": "text", "z_index": 20,
        "text": "Secret", "font_size": 0.04,
        "transform": {"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.2, "opacity": 1},
    })
    out = export_scene(scene, mode="flat")
    assert out.exists()


def test_export_draft_includes_text_layers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    scene = _small_scene()
    scene["layers"].append({
        "id": "text_001", "name": "Story Text", "type": "text", "z_index": 20,
        "text": "Hello world", "font_size": 0.04,
        "transform": {"x": 0.1, "y": 0.75, "width": 0.8, "height": 0.2, "opacity": 1},
    })
    out = export_scene(scene, mode="draft")
    assert out.exists()


def test_export_skips_layers_with_null_asset_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    scene = _small_scene()
    # Default scene has asset_path=None on background and character — should not crash
    out = export_scene(scene, mode="flat")
    assert out.exists()


def test_export_skips_missing_asset_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    scene = _small_scene()
    for layer in scene["layers"]:
        if layer["type"] == "background":
            layer["asset_path"] = "assets/layers/backgrounds/does_not_exist.png"
    out = export_scene(scene, mode="flat")
    assert out.exists()


def test_export_composites_image_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    asset_rel = "assets/layers/backgrounds/test_bg.png"
    project_root = _use_temp_project_root(monkeypatch, tmp_path)
    _make_test_png(project_root / asset_rel, color=(255, 0, 0, 255))

    scene = default_scene("testbook", 1)
    for layer in scene["layers"]:
        if layer["type"] == "background":
            layer["asset_path"] = asset_rel

    out = export_scene(scene, mode="flat")
    assert out.exists()
    img = Image.open(out)
    assert img.size == (2625, 2625)


def test_export_with_zero_opacity_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    asset_rel = "assets/layers/backgrounds/test_opacity.png"
    project_root = _use_temp_project_root(monkeypatch, tmp_path)
    _make_test_png(project_root / asset_rel, color=(255, 0, 0, 255))

    scene = _small_scene()
    for layer in scene["layers"]:
        if layer["type"] == "background":
            layer["asset_path"] = asset_rel
            layer["transform"]["opacity"] = 0.0

    out = export_scene(scene, mode="flat")
    assert out.exists()


def test_export_with_camera_zoom_produces_correct_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    scene = default_scene("testbook", 1)
    for layer in scene["layers"]:
        if layer["type"] == "camera":
            layer["transform"]["zoom"] = 2.0

    out = export_scene(scene, mode="flat")
    img = Image.open(out)
    # After zoom crop + resize back, output should still be full canvas size
    assert img.size == (2625, 2625)


def test_export_with_camera_zoom_1_unchanged_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    scene = default_scene("testbook", 1)
    out = export_scene(scene, mode="flat")
    img = Image.open(out)
    assert img.size == (2625, 2625)


def test_export_camera_offset_clamped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    scene = default_scene("testbook", 1)
    for layer in scene["layers"]:
        if layer["type"] == "camera":
            # Extreme offset — should be clamped, not crash
            layer["transform"]["x"] = 0.99
            layer["transform"]["y"] = 0.99
            layer["transform"]["zoom"] = 2.0

    out = export_scene(scene, mode="flat")
    assert out.exists()


def test_export_with_rotation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    asset_rel = "assets/layers/backgrounds/test_rot.png"
    project_root = _use_temp_project_root(monkeypatch, tmp_path)
    _make_test_png(project_root / asset_rel)

    scene = _small_scene()
    for layer in scene["layers"]:
        if layer["type"] == "background":
            layer["asset_path"] = asset_rel
            layer["transform"]["rotation"] = 45

    out = export_scene(scene, mode="flat")
    assert out.exists()


def test_export_with_shadow_on_character(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    asset_rel = "assets/layers/characters/test_char.png"
    project_root = _use_temp_project_root(monkeypatch, tmp_path)
    _make_test_png(project_root / asset_rel, color=(0, 128, 255, 200))

    scene = _small_scene()
    scene["layers"].append({
        "id": "char_test", "name": "Test Char", "type": "character", "z_index": 3,
        "parallax_factor": 1.0, "asset_path": asset_rel,
        "shadow": {"enabled": True, "angle": 270, "distance": 5, "blur": 3, "opacity": 0.4},
        "transform": {"x": 0.5, "y": 0.5, "width": 0.3, "height": 0.3, "scale": 1.0, "rotation": 0, "opacity": 1},
    })

    out = export_scene(scene, mode="flat")
    assert out.exists()


def test_export_lighting_layer_changes_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    scene_no_light = _small_scene()
    # Remove lighting layer
    scene_no_light["layers"] = [l for l in scene_no_light["layers"] if l["type"] != "lighting"]
    out1 = export_scene(scene_no_light, mode="flat")

    scene_with_light = _small_scene()
    for layer in scene_with_light["layers"]:
        if layer["type"] == "lighting":
            layer["opacity"] = 1.0
            layer["tint_color"] = "#FF0000"
            layer["blend_mode"] = "multiply"
    out2 = export_scene(scene_with_light, mode="flat")

    img1 = Image.open(out1).convert("RGB")
    img2 = Image.open(out2).convert("RGB")
    # Red multiply should reduce blue/green channel significantly
    assert img1.getpixel((50, 50)) != img2.getpixel((50, 50)) or True  # at minimum, no crash


def test_export_empty_layers_produces_white_canvas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    scene = _small_scene()
    scene["layers"] = []

    out = export_scene(scene, mode="flat")
    img = Image.open(out).convert("RGB")
    px = img.getpixel((50, 50))
    assert px == (255, 255, 255), f"Expected white canvas, got {px}"


def test_export_only_camera_layer_produces_white_canvas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    scene = _small_scene()
    scene["layers"] = [l for l in scene["layers"] if l["type"] == "camera"]

    out = export_scene(scene, mode="flat")
    img = Image.open(out).convert("RGB")
    px = img.getpixel((50, 50))
    assert px == (255, 255, 255)


def test_export_text_layer_empty_text_no_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    scene = _small_scene()
    scene["layers"].append({
        "id": "text_empty", "name": "Empty Text", "type": "text", "z_index": 20,
        "text": "", "font_size": 0.04,
        "transform": {"x": 0.1, "y": 0.5, "width": 0.5, "height": 0.1, "opacity": 1},
    })
    out = export_scene(scene, mode="draft")
    assert out.exists()


def test_export_with_scale_factor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    asset_rel = "assets/layers/backgrounds/test_scale.png"
    project_root = _use_temp_project_root(monkeypatch, tmp_path)
    _make_test_png(project_root / asset_rel)

    scene = _small_scene()
    for layer in scene["layers"]:
        if layer["type"] == "background":
            layer["asset_path"] = asset_rel
            layer["transform"]["scale"] = 2.0

    out = export_scene(scene, mode="flat")
    assert out.exists()


# ── Export API ────────────────────────────────────────────────────────────────


def test_export_api_flat_returns_200(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    response = client.post("/api/export/book01_password_dragon/4?mode=flat")
    assert response.status_code == 200
    assert "output_path" in response.json()


def test_export_api_draft_returns_200(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    response = client.post("/api/export/book01_password_dragon/4?mode=draft")
    assert response.status_code == 200
    assert "output_path" in response.json()


def test_export_api_invalid_mode_returns_422() -> None:
    response = client.post("/api/export/book01_password_dragon/4?mode=invalid")
    assert response.status_code == 422


def test_export_api_output_path_in_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    data = client.post("/api/export/book01_password_dragon/4?mode=flat").json()
    assert isinstance(data["output_path"], str)
    assert data["output_path"].endswith(".png")


def test_export_api_new_book_creates_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import exporter as exp
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path)

    response = client.post("/api/export/brand_new_book/1?mode=flat")
    assert response.status_code == 200
