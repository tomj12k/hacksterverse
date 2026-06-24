"""Tests for the scene schema service and story-maker API routes."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from hackster_studio.database import engine
from hackster_studio.main import app
from hackster_studio.models import Book, Page
from hackster_studio.services.story_maker import (
    SCENE_ROOT,
    book_readiness,
    book_page_count,
    default_scene,
    load_scene,
    review_image_layer,
    review_text_layer,
    save_scene,
    scene_path,
    validate_scene,
)

client = TestClient(app)


def cleanup_book(slug: str) -> None:
    with Session(engine) as session:
        book = session.exec(select(Book).where(Book.slug == slug)).first()
        if book is None or book.id is None:
            return
        for page in session.exec(select(Page).where(Page.book_id == book.id)).all():
            session.delete(page)
        session.delete(book)
        session.commit()


# ── scene_path ────────────────────────────────────────────────────────────────


def test_scene_path_format() -> None:
    p = scene_path("mybook", 3)
    assert p.name == "page_003.scene.json"
    assert p.parent.name == "mybook"


def test_scene_path_pads_to_three_digits() -> None:
    assert scene_path("b", 1).name == "page_001.scene.json"
    assert scene_path("b", 10).name == "page_010.scene.json"
    assert scene_path("b", 999).name == "page_999.scene.json"


def test_scene_path_under_scene_root() -> None:
    p = scene_path("mybook", 1)
    assert p.is_relative_to(SCENE_ROOT)


def test_scene_path_rejects_traversal_slug() -> None:
    with pytest.raises(ValueError):
        scene_path("..", 1)


def test_scene_path_rejects_non_positive_page_number() -> None:
    with pytest.raises(ValueError):
        scene_path("mybook", 0)


# ── default_scene structure ───────────────────────────────────────────────────


def test_default_scene_has_required_top_level_keys() -> None:
    scene = default_scene("book01_password_dragon", 4)
    assert scene["book_slug"] == "book01_password_dragon"
    assert scene["page_number"] == 4
    assert "canvas" in scene
    assert "lighting_brief" in scene
    assert isinstance(scene["layers"], list)
    assert scene["status"] == "not_started"
    assert "approval" in scene
    assert "qa" in scene


def test_default_scene_layers_have_production_fields() -> None:
    scene = default_scene("book01_password_dragon", 4)
    for layer in scene["layers"]:
        assert "visible" in layer
        assert "versions" in layer
        assert "prompt_history" in layer


def test_validate_scene_flags_text_outside_safe_area() -> None:
    scene = default_scene("book01_password_dragon", 4)
    text = next(layer for layer in scene["layers"] if layer["type"] == "text")
    text["transform"]["x"] = 0.02
    qa = validate_scene(scene)

    assert qa["errors"] >= 1
    assert any(issue["code"] == "text_outside_safe_area" for issue in qa["issues"])


def test_apply_text_style_to_all_pages_preserves_page_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import story_maker as sm

    monkeypatch.setattr(sm, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path / "scenes")
    monkeypatch.setattr(sm, "LAYERS_DIR", tmp_path / "assets" / "layers")

    pages_dir = tmp_path / "books" / "demo_book" / "pages"
    illustrations_dir = tmp_path / "books" / "demo_book" / "illustrations"
    pages_dir.mkdir(parents=True)
    illustrations_dir.mkdir(parents=True)
    for page_number, words in [(1, "First page words."), (2, "Second page words.")]:
        (pages_dir / f"page_{page_number:03d}.yaml").write_text(f"story_text: {words!r}\n", encoding="utf-8")
        (illustrations_dir / f"page_{page_number:03d}.png").write_bytes(b"fake")

    source = sm.default_scene("demo_book", 1)
    source_text = next(layer for layer in source["layers"] if layer["type"] == "text")
    source_text["font_size"] = 0.08
    source_text["text_color"] = "#ff0000"
    source_text["transform"]["x"] = 0.45
    source_text["transform"]["y"] = 0.75
    sm.save_scene(source)

    result = sm.apply_text_style_to_all_pages("demo_book", 1, layer_id="page_text")
    updated = sm.load_scene("demo_book", 2)
    text = next(layer for layer in updated["layers"] if layer["type"] == "text")

    assert result["updated_count"] == 2
    assert text["text"] == "Second page words."
    assert text["font_size"] == 0.08
    assert text["text_color"] == "#ff0000"
    assert text["transform"]["x"] == 0.45
    assert text["transform"]["y"] == 0.75
    assert text["asset_path"] is None


def test_default_scene_canvas_spec() -> None:
    canvas = default_scene("book01_password_dragon", 4)["canvas"]
    assert canvas["width_px"] == 2625
    assert canvas["height_px"] == 2625
    assert canvas["dpi"] == 300
    assert canvas["bleed_inches"] == 0.125
    assert canvas["safe_margin_inches"] == 0.5


def test_default_scene_lighting_brief() -> None:
    assert default_scene("b", 1)["lighting_brief"] == "ambient_soft"


def test_default_scene_has_camera_layer() -> None:
    types = [lay["type"] for lay in default_scene("b", 1)["layers"]]
    assert "camera" in types


def test_default_scene_camera_z_index() -> None:
    cam = next(l for l in default_scene("b", 1)["layers"] if l["type"] == "camera")
    assert cam["z_index"] == 99


def test_default_scene_camera_has_zoom() -> None:
    cam = next(l for l in default_scene("b", 1)["layers"] if l["type"] == "camera")
    assert "zoom" in cam["transform"]
    assert cam["transform"]["zoom"] == 1.0


def test_default_scene_has_lighting_layer() -> None:
    types = [lay["type"] for lay in default_scene("b", 1)["layers"]]
    assert "lighting" in types


def test_default_scene_lighting_z_index() -> None:
    lit = next(l for l in default_scene("b", 1)["layers"] if l["type"] == "lighting")
    assert lit["z_index"] == 10


def test_default_scene_lighting_fields() -> None:
    lit = next(l for l in default_scene("b", 1)["layers"] if l["type"] == "lighting")
    assert "tint_color" in lit
    assert "blend_mode" in lit
    assert "opacity" in lit
    assert lit["opacity"] == 0.0


def test_default_scene_does_not_add_niko_to_generic_books() -> None:
    chars = [l for l in default_scene("b", 1)["layers"] if l["type"] == "character"]
    assert chars == []


def test_default_scene_adds_niko_to_hackster_books(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import story_maker as sm

    monkeypatch.setattr(sm, "PROJECT_ROOT", tmp_path)
    book_dir = tmp_path / "books" / "hackster_demo"
    book_dir.mkdir(parents=True)
    (book_dir / "book.yaml").write_text("title: Hackster Niko and the Test\n", encoding="utf-8")

    chars = [l for l in sm.default_scene("hackster_demo", 1)["layers"] if l["type"] == "character"]
    assert chars
    niko = chars[0]
    assert niko["character_slug"] == "niko"
    assert "shadow" in niko
    assert niko["shadow"]["enabled"] is False
    assert niko["rig"] is None


def test_default_scene_character_z_index_for_hackster_books(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import story_maker as sm

    monkeypatch.setattr(sm, "PROJECT_ROOT", tmp_path)
    book_dir = tmp_path / "books" / "hackster_demo"
    book_dir.mkdir(parents=True)
    (book_dir / "book.yaml").write_text("title: Hackster Niko and the Test\n", encoding="utf-8")

    char = next(l for l in sm.default_scene("hackster_demo", 1)["layers"] if l["type"] == "character")
    assert char["z_index"] == 3


def test_default_scene_has_background_layer() -> None:
    types = [lay["type"] for lay in default_scene("b", 1)["layers"]]
    assert "background" in types


def test_default_scene_background_z_index() -> None:
    bg = next(l for l in default_scene("b", 1)["layers"] if l["type"] == "background")
    assert bg["z_index"] == 0


def test_review_image_layer_covers_full_page() -> None:
    layer = review_image_layer("books/book01/illustrations/page_001.png")
    assert layer["id"] == "book_illustration"
    assert layer["locked"] is True
    assert layer["z_index"] == 0
    assert layer["transform"]["x"] == 0.5
    assert layer["transform"]["width"] == 1.0


def test_review_text_layer_uses_story_text() -> None:
    layer = review_text_layer('"Hello," said Niko.')
    assert layer["id"] == "page_text"
    assert layer["type"] == "text"
    assert layer["text"] == '"Hello," said Niko.'
    assert layer["transform"]["y"] > 0.5


def test_default_scene_hydrates_existing_book_illustration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import story_maker as sm

    monkeypatch.setattr(sm, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path / "scenes")
    image_path = tmp_path / "books" / "demo_book" / "illustrations" / "page_002.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"fake")

    scene = sm.default_scene("demo_book", 2)
    layer = next(l for l in scene["layers"] if l["id"] == "book_illustration")
    layer_ids = {l["id"] for l in scene["layers"]}
    assert layer["asset_path"] == "books/demo_book/illustrations/page_002.png"
    assert isinstance(layer["asset_version"], int)
    assert scene["book_illustration_version"] == layer["asset_version"]
    assert scene["book_illustration_path"] == "books/demo_book/illustrations/page_002.png"
    assert "char_niko" not in layer_ids
    assert "bg_001" not in layer_ids


def test_refresh_scene_image_from_page_updates_existing_layer_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio import main as main_mod
    from hackster_studio.services import story_maker as sm

    monkeypatch.setattr(sm, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path / "scenes")
    monkeypatch.setattr(main_mod, "PROJECT_ROOT", tmp_path)
    image_path = tmp_path / "books" / "demo_book" / "illustrations" / "page_010.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"old")

    scene = sm.default_scene("demo_book", 10)
    sm.save_scene(scene)
    old_version = next(layer for layer in scene["layers"] if layer["id"] == "book_illustration")["asset_version"]
    image_path.write_bytes(b"new image contents")

    new_version = main_mod._refresh_scene_image_from_page("demo_book", 10)
    refreshed = sm.load_scene("demo_book", 10)
    layer = next(layer for layer in refreshed["layers"] if layer["id"] == "book_illustration")

    assert new_version is not None
    assert new_version != old_version
    assert refreshed["book_illustration_version"] == new_version
    assert layer["asset_version"] == new_version
    assert layer["asset_path"] == "books/demo_book/illustrations/page_010.png"


def test_default_scene_adds_story_text_layer_from_page_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import story_maker as sm

    monkeypatch.setattr(sm, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path / "scenes")
    image_path = tmp_path / "books" / "demo_book" / "illustrations" / "page_002.png"
    page_path = tmp_path / "books" / "demo_book" / "pages" / "page_002.yaml"
    image_path.parent.mkdir(parents=True)
    page_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"fake")
    page_path.write_text('story_text: "\\"Every problem has a clever fix!\\" said Niko."\n', encoding="utf-8")

    scene = sm.default_scene("demo_book", 2)
    text_layer = next(layer for layer in scene["layers"] if layer["id"] == "page_text")

    assert text_layer["type"] == "text"
    assert text_layer["text"] == '"Every problem has a clever fix!" said Niko.'
    assert scene["story_text"] == text_layer["text"]


def test_default_scene_exposes_planned_characters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import story_maker as sm

    monkeypatch.setattr(sm, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sm, "LAYERS_DIR", tmp_path / "assets" / "layers")
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path / "scenes")
    book_dir = tmp_path / "books" / "samurai_splat"
    pages_dir = book_dir / "pages"
    pages_dir.mkdir(parents=True)
    (book_dir / "book.yaml").write_text(
        yaml.safe_dump({
            "title": "Samurai Splat",
            "planner_brief": {
                "focus_characters": ["Samurai Splat", "Shotgun Bob"],
            },
        }),
        encoding="utf-8",
    )
    (pages_dir / "page_001.yaml").write_text(
        yaml.safe_dump({"characters": ["Samurai Splat", "Noodle Cook"]}),
        encoding="utf-8",
    )
    asset_dir = tmp_path / "assets" / "layers" / "characters" / "samurai_splat"
    asset_dir.mkdir(parents=True)
    (asset_dir / "samurai_splat_front.png").write_bytes(b"fake")

    scene = sm.default_scene("samurai_splat", 1)

    characters = {character["name"]: character for character in scene["planned_characters"]}
    assert set(characters) == {"Samurai Splat", "Shotgun Bob", "Noodle Cook"}
    assert characters["Samurai Splat"]["slug"] == "samurai_splat"
    assert characters["Samurai Splat"]["asset_paths"] == [
        "assets/layers/characters/samurai_splat/samurai_splat_front.png"
    ]


def test_default_scene_adds_posable_niko_for_review_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import story_maker as sm

    monkeypatch.setattr(sm, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sm, "LAYERS_DIR", tmp_path / "assets" / "layers")
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path / "scenes")
    book_dir = tmp_path / "books" / "demo_book"
    book_dir.mkdir(parents=True)
    (book_dir / "book.yaml").write_text("title: Hackster Niko and the Test\n", encoding="utf-8")
    image_path = book_dir / "illustrations" / "page_004.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"fake")

    scene = sm.default_scene("demo_book", 4)
    niko = next(l for l in scene["layers"] if l["id"] == "char_niko")

    assert niko["type"] == "character"
    assert niko["pose"] == "walk_front"
    assert niko["asset_path"] == "assets/layers/characters/niko/niko_walk_front.png"
    assert (tmp_path / niko["asset_path"]).exists()
    assert niko["rig"]["type"] == "niko_simple_v3"
    assert {bone["id"] for bone in niko["rig"]["bones"]} == {
        "body_lean", "head_tilt", "antenna_tilt",
        "left_upper_arm", "left_forearm", "left_hand",
        "right_upper_arm", "right_forearm", "right_hand",
        "left_thigh", "left_shin", "left_foot",
        "right_thigh", "right_shin", "right_foot",
    }
    assert niko["transform"]["x"] == pytest.approx(0.42)
    assert niko["transform"]["height"] == pytest.approx(0.48)


def test_remove_hackster_niko_from_book_suppresses_all_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import story_maker as sm

    monkeypatch.setattr(sm, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sm, "LAYERS_DIR", tmp_path / "assets" / "layers")
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path / "scenes")
    book_dir = tmp_path / "books" / "hackster_demo"
    pages_dir = book_dir / "pages"
    pages_dir.mkdir(parents=True)
    (book_dir / "book.yaml").write_text("title: Hackster Niko and the Test\n", encoding="utf-8")
    for page_number in range(1, 3):
        (pages_dir / f"page_{page_number:03d}.yaml").write_text("story_text: Test\n", encoding="utf-8")

    result = sm.remove_hackster_niko_from_book("hackster_demo")
    scene = sm.load_scene("hackster_demo", 1)

    assert result["pages_updated"] == 2
    assert scene["suppress_hackster_niko"] is True
    assert scene["uses_hackster_niko"] is False
    assert all(layer["id"] != "char_niko" for layer in scene["layers"])


def test_book_page_count_uses_book_pages_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import story_maker as sm

    monkeypatch.setattr(sm, "PROJECT_ROOT", tmp_path)
    pages_dir = tmp_path / "books" / "demo_book" / "pages"
    pages_dir.mkdir(parents=True)
    for page in range(1, 4):
        (pages_dir / f"page_{page:03d}.yaml").write_text("page_number: 1\n", encoding="utf-8")

    assert book_page_count("demo_book") == 3


def test_default_scene_all_layers_have_id() -> None:
    for layer in default_scene("b", 1)["layers"]:
        assert "id" in layer, f"Layer missing id: {layer}"


def test_default_scene_layer_ids_unique() -> None:
    ids = [lay["id"] for lay in default_scene("b", 1)["layers"]]
    assert len(ids) == len(set(ids))


def test_default_scene_all_layers_have_z_index() -> None:
    for layer in default_scene("b", 1)["layers"]:
        assert "z_index" in layer


def test_default_scene_book_slug_and_page_respected() -> None:
    s = default_scene("other_book", 7)
    assert s["book_slug"] == "other_book"
    assert s["page_number"] == 7


# ── save_scene ────────────────────────────────────────────────────────────────


def test_save_scene_missing_book_slug_raises() -> None:
    with pytest.raises(ValueError, match="book_slug"):
        save_scene({"page_number": 1, "layers": []})


def test_save_scene_missing_page_number_raises() -> None:
    with pytest.raises(ValueError, match="page_number"):
        save_scene({"book_slug": "b", "layers": []})


def test_save_scene_missing_both_keys_raises() -> None:
    with pytest.raises(ValueError):
        save_scene({"layers": []})


def test_save_scene_creates_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import story_maker as sm
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path)

    scene = default_scene("testbook", 1)
    path = save_scene(scene)
    assert path.exists()
    assert path.suffix == ".json"


def test_save_scene_creates_parent_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import story_maker as sm
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path / "nested" / "deeper")

    save_scene(default_scene("testbook", 1))
    assert (tmp_path / "nested" / "deeper" / "testbook" / "page_001.scene.json").exists()


def test_save_scene_writes_valid_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import story_maker as sm
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path)

    scene = default_scene("testbook", 1)
    path = save_scene(scene)
    parsed = json.loads(path.read_text())
    assert parsed["book_slug"] == "testbook"


def test_save_scene_preserves_all_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import story_maker as sm
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path)

    scene = default_scene("testbook", 2)
    scene["lighting_brief"] = "warm_sunset_left"
    scene["custom_field"] = "extra_data"
    path = save_scene(scene)

    loaded = json.loads(path.read_text())
    assert loaded["lighting_brief"] == "warm_sunset_left"
    assert loaded["custom_field"] == "extra_data"


def test_save_scene_preserves_unicode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import story_maker as sm
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path)

    scene = default_scene("testbook", 1)
    scene["layers"][0]["name"] = "日本語テスト"
    path = save_scene(scene)

    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["layers"][0]["name"] == "日本語テスト"


def test_save_scene_overwrites_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import story_maker as sm
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path)

    scene = default_scene("testbook", 1)
    save_scene(scene)
    scene["lighting_brief"] = "dramatic_backlight"
    save_scene(scene)

    loaded = json.loads((tmp_path / "testbook" / "page_001.scene.json").read_text())
    assert loaded["lighting_brief"] == "dramatic_backlight"


# ── load_scene ────────────────────────────────────────────────────────────────


def test_load_scene_returns_default_when_file_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import story_maker as sm
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path)

    scene = load_scene("unknown_book", 99)
    assert scene["book_slug"] == "unknown_book"
    assert scene["page_number"] == 99


def test_load_scene_returns_saved_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import story_maker as sm
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path)

    original = default_scene("testbook", 1)
    original["lighting_brief"] = "cool_forest_ambient"
    save_scene(original)

    loaded = load_scene("testbook", 1)
    assert loaded["lighting_brief"] == "cool_forest_ambient"


def test_save_and_reload_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import story_maker as sm
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path)

    scene = default_scene("testbook", 1)
    save_scene(scene)
    loaded = load_scene("testbook", 1)
    assert loaded["book_slug"] == "testbook"
    assert loaded["page_number"] == 1
    assert len(loaded["layers"]) == len(scene["layers"])


# ── Story Maker HTML route ────────────────────────────────────────────────────


def test_story_maker_route_renders() -> None:
    response = client.get("/story-maker")
    assert response.status_code == 200
    assert "Story Maker" in response.text


def test_story_maker_html_has_scene_data_script() -> None:
    response = client.get("/story-maker")
    assert 'id="story-scene-data"' in response.text
    assert "application/json" in response.text


def test_story_maker_html_has_asset_browser_dialog() -> None:
    response = client.get("/story-maker")
    assert 'data-asset-browser' in response.text
    assert '<dialog' in response.text


def test_story_maker_html_has_story_cast_panel() -> None:
    response = client.get("/story-maker")
    assert 'data-story-cast' in response.text
    assert "Planned Characters" in response.text


def test_story_maker_html_script_after_dialog() -> None:
    response = client.get("/story-maker")
    dialog_pos = response.text.index("data-asset-browser")
    script_pos = response.text.index("story_maker.js")
    assert script_pos > dialog_pos, "story_maker.js must be loaded after the <dialog>"


def test_story_maker_html_has_add_layer_button() -> None:
    response = client.get("/story-maker")
    assert 'data-action="add-layer"' in response.text


def test_story_maker_html_has_delete_layer_button() -> None:
    response = client.get("/story-maker")
    assert 'data-action="delete-layer"' in response.text


def test_story_maker_html_has_add_text_button() -> None:
    response = client.get("/story-maker")
    assert 'data-action="add-text"' in response.text


def test_story_maker_html_has_zoom_control() -> None:
    response = client.get("/story-maker")
    assert 'data-control="zoom"' in response.text


def test_story_maker_html_has_inspector_extras_div() -> None:
    response = client.get("/story-maker")
    assert "data-inspector-extras" in response.text


def test_story_maker_html_has_layer_list() -> None:
    response = client.get("/story-maker")
    assert "data-layer-list" in response.text


def test_story_maker_html_has_stage() -> None:
    response = client.get("/story-maker")
    assert "data-story-stage" in response.text


def test_story_maker_html_has_page_navigation() -> None:
    response = client.get("/story-maker?book_slug=book01_password_dragon&page=4")
    assert "Previous" in response.text
    assert "Next" in response.text
    assert 'name="page"' in response.text


def test_story_maker_html_has_promote_button() -> None:
    response = client.get("/story-maker?book_slug=book01_password_dragon&page=4")
    assert 'data-action="promote-flat"' in response.text


def test_story_maker_html_has_production_controls() -> None:
    response = client.get("/story-maker?book_slug=book01_password_dragon&page=4")
    assert "data-page-status-control" in response.text
    assert "data-action=\"approve-page\"" in response.text
    assert "data-qa-panel" in response.text
    assert "data-guide=\"safe\"" in response.text
    assert "data-grid-toggle" in response.text
    assert "data-snap-toggle" in response.text


def test_book_assembly_route_renders() -> None:
    response = client.get("/book-assembly?book_slug=book01_password_dragon")
    assert response.status_code == 200
    assert "Book Assembly" in response.text
    assert "Page 001" in response.text


def test_workflow_points_to_book_generation_page() -> None:
    response = client.get("/workflow?book_slug=book01_password_dragon")
    assert response.status_code == 200
    assert "Generate Book" in response.text
    assert "/book-generation?book_slug=book01_password_dragon" in response.text


def test_top_navigation_uses_grouped_hierarchy() -> None:
    response = client.get("/workflow?book_slug=book01_password_dragon")

    assert response.status_code == 200
    assert 'class="nav-primary"' in response.text
    assert 'class="nav-groups"' in response.text
    assert "<summary>Pipeline</summary>" in response.text
    assert "<summary>Libraries</summary>" in response.text
    assert "<summary>System</summary>" in response.text
    assert "/generate?book_slug=book01_password_dragon" in response.text
    assert "/story-maker?book_slug=book01_password_dragon&amp;page=1" in response.text


def test_books_page_has_create_form() -> None:
    response = client.get("/books")
    assert response.status_code == 200
    assert "Create Book" in response.text
    assert 'action="/books"' in response.text
    assert 'name="idea"' in response.text
    assert 'name="characters"' in response.text
    assert 'name="objects"' in response.text
    assert "Create + Generate with DGX" in response.text
    assert "Create + Generate with OpenAI" not in response.text


def test_create_book_route_creates_files_and_sets_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import books as bs
    from hackster_studio.services import story_maker as sm

    monkeypatch.setattr(bs, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sm, "PROJECT_ROOT", tmp_path)
    response = client.post(
        "/books",
        data={
            "title": "Hackster Niko and the Test Book",
            "slug": "test_book",
            "series": "Hackster Niko",
            "target_age": "5-8",
            "page_count": "4",
            "trim_size": "8.5x8.5",
            "lesson": "Testing current book switching.",
        },
        follow_redirects=False,
    )

    created_slug = response.headers["location"].rsplit("/", 1)[-1]
    assert response.status_code == 303
    assert response.headers["location"] == f"/books/{created_slug}"
    assert f"hackster_current_book={created_slug}" in response.headers["set-cookie"]
    cleanup_book(created_slug)


def test_create_book_service_creates_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlmodel import SQLModel, create_engine
    from hackster_studio.services import books as bs

    monkeypatch.setattr(bs, "PROJECT_ROOT", tmp_path)
    local_engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(local_engine)
    with Session(local_engine) as session:
        book = bs.create_book(session, title="Service Book", slug="service_book", page_count=4)

    assert (tmp_path / "books" / book.slug / "book.yaml").exists()
    assert (tmp_path / "books" / book.slug / "pages" / "page_004.yaml").exists()


def test_delete_book_service_removes_database_rows_and_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlmodel import SQLModel, create_engine
    from hackster_studio.services import books as bs
    from hackster_studio.models import Prompt

    monkeypatch.setattr(bs, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(bs, "GENERATED_DIR", tmp_path / "data" / "generated")
    monkeypatch.setattr(bs, "LAYERS_DIR", tmp_path / "assets" / "layers")
    monkeypatch.setenv("HACKSTER_SCENE_ROOT", str(tmp_path / "storybook_scenes"))

    local_engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(local_engine)
    with Session(local_engine) as session:
        book = bs.create_book(session, title="Delete Me", slug="delete_me", page_count=2)
        pages = bs.get_pages_for_book(session, book.id or 0)
        session.add(
            Prompt(
                prompt_type="book_page_illustration",
                related_type="page",
                related_id=pages[0].id or 0,
                title="Delete prompt",
                output_path="data/generated/prompts/pages/delete_me/page_01.md",
            )
        )
        session.commit()

        (tmp_path / "data" / "generated" / "page_specs" / book.slug).mkdir(parents=True)
        (tmp_path / "data" / "generated" / "page_specs" / book.slug / "page_01.yaml").write_text("ok", encoding="utf-8")
        (tmp_path / "storybook_scenes" / book.slug).mkdir(parents=True)
        (tmp_path / "storybook_scenes" / book.slug / "page_001.scene.json").write_text("{}", encoding="utf-8")
        (tmp_path / "assets" / "layers" / "text" / book.slug).mkdir(parents=True)
        (tmp_path / "assets" / "layers" / "text" / book.slug / "title.png").write_bytes(b"")
        custom_dir = tmp_path / "assets" / "layers" / "characters" / "splat" / "custom"
        custom_dir.mkdir(parents=True)
        (custom_dir / f"{book.slug}_page_001_splat.png").write_bytes(b"")

        bs.delete_book(session, book.slug)

        assert bs.get_book_by_slug(session, book.slug) is None
        assert session.exec(select(Page).where(Page.book_id == book.id)).all() == []
        assert session.exec(select(Prompt).where(Prompt.related_type == "page")).all() == []

    assert not (tmp_path / "books" / "delete_me").exists()
    assert not (tmp_path / "data" / "generated" / "page_specs" / "delete_me").exists()
    assert not (tmp_path / "storybook_scenes" / "delete_me").exists()
    assert not (tmp_path / "assets" / "layers" / "text" / "delete_me").exists()
    assert not (tmp_path / "assets" / "layers" / "characters" / "splat" / "custom" / "delete_me_page_001_splat.png").exists()


def test_generate_book_from_brief_fills_pages_and_brief(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlmodel import SQLModel, create_engine
    from hackster_studio.services import books as bs

    monkeypatch.setattr(bs, "PROJECT_ROOT", tmp_path)
    local_engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(local_engine)
    with Session(local_engine) as session:
        book = bs.create_book(session, title="Weather Machine", slug="weather_machine", page_count=8)
        pages = bs.generate_book_from_brief(
            session,
            book.slug,
            idea="Niko helps a shy cloud debug a weather machine.",
            characters="Hackster Niko, Cloudy, Byte",
            objects="Golden Gear, Weather Wand",
            character_count=3,
            object_count=2,
            reference_notes="Cloudy is soft blue and round.",
        )

        stored_pages = session.exec(select(Page).where(Page.book_id == book.id)).all()
        refreshed_book = session.get(Book, book.id)

    book_yaml = yaml.safe_load((tmp_path / "books" / book.slug / "book.yaml").read_text(encoding="utf-8"))
    page_yaml = yaml.safe_load(
        (tmp_path / "books" / book.slug / "pages" / "page_004.yaml").read_text(encoding="utf-8")
    )
    brief_yaml = yaml.safe_load((tmp_path / "books" / book.slug / "planning_brief.yaml").read_text(encoding="utf-8"))

    assert len(pages) == 8
    assert len(stored_pages) == 8
    assert refreshed_book is not None
    assert refreshed_book.status == "book plan generated"
    assert brief_yaml["idea"] == "Niko helps a shy cloud debug a weather machine."
    assert "Cloudy" in brief_yaml["focus_characters"]
    assert "Weather Wand" in brief_yaml["focus_items"]
    assert book_yaml["planner_brief"]["reference_notes"] == "Cloudy is soft blue and round."
    assert "weather machine" in page_yaml["illustration_direction"]
    assert page_yaml["status"] == "planned"


def test_create_book_route_can_generate_full_book_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import books as bs
    from hackster_studio.services import exports as ex
    from hackster_studio.services import prompts as ps
    from hackster_studio.services import story_maker as sm

    monkeypatch.setattr(bs, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ex, "GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(ps, "GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(ps, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sm, "PROJECT_ROOT", tmp_path)
    response = client.post(
        "/books",
        data={
            "title": "Hackster Niko and the Cloud Console",
            "slug": f"cloud_console_{tmp_path.name}",
            "series": "Hackster Niko",
            "target_age": "5-8",
            "page_count": "6",
            "trim_size": "8.5x8.5",
            "lesson": "",
            "idea": "Niko teaches a cloud console to ask for help before making changes.",
            "characters": "Hackster Niko, Cloud Console, Byte",
            "objects": "Golden Gear, Blue Crystal",
            "character_count": "3",
            "object_count": "2",
            "reference_notes": "Cloud Console has a friendly glowing screen.",
            "generate_book": "1",
        },
        follow_redirects=False,
    )

    created_slug = response.headers["location"].rsplit("/", 1)[-1]
    brief_path = tmp_path / "books" / created_slug / "planning_brief.yaml"
    page_path = tmp_path / "books" / created_slug / "pages" / "page_004.yaml"
    page_specs_dir = tmp_path / "generated" / "page_specs" / created_slug
    prompts_dir = tmp_path / "generated" / "prompts" / "pages" / created_slug
    page_yaml = yaml.safe_load(page_path.read_text(encoding="utf-8"))

    assert response.status_code == 303
    assert brief_path.exists()
    assert (page_specs_dir / "page_04.yaml").exists()
    assert len(list(prompts_dir.glob("*.md"))) == 6
    assert "cloud console" in brief_path.read_text(encoding="utf-8").lower()
    assert "cloud console" in page_yaml["illustration_direction"].lower()
    assert f"hackster_current_book={created_slug}" in response.headers["set-cookie"]
    cleanup_book(created_slug)


def test_delete_book_route_removes_book_and_generated_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hackster_studio.main as main_mod
    from hackster_studio.services import books as bs

    monkeypatch.setattr(bs, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(bs, "GENERATED_DIR", tmp_path / "data" / "generated")
    monkeypatch.setattr(bs, "LAYERS_DIR", tmp_path / "assets" / "layers")
    monkeypatch.setenv("HACKSTER_SCENE_ROOT", str(tmp_path / "storybook_scenes"))
    slug = f"route_delete_{tmp_path.name}"

    create_response = client.post(
        "/books",
        data={"title": "Route Delete", "slug": slug, "page_count": "2"},
        follow_redirects=False,
    )
    created_slug = create_response.headers["location"].rsplit("/", 1)[-1]
    (tmp_path / "data" / "generated" / "prompts" / "pages" / created_slug).mkdir(parents=True)
    (tmp_path / "data" / "generated" / "prompts" / "pages" / created_slug / "page_01.md").write_text("prompt", encoding="utf-8")
    with main_mod._book_generation_jobs_lock:
        main_mod._book_generation_jobs["delete-route-job"] = main_mod.BookGenerationJob(
            job_id="delete-route-job",
            book_slug=created_slug,
            redirect_url=f"/workflow?book_slug={created_slug}",
            status="running",
        )

    response = client.post(
        f"/books/{created_slug}/delete",
        cookies={"hackster_current_book": created_slug},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/books"
    assert "hackster_current_book" in response.headers.get("set-cookie", "")
    assert not (tmp_path / "books" / created_slug).exists()
    assert not (tmp_path / "data" / "generated" / "prompts" / "pages" / created_slug).exists()
    with main_mod._book_generation_jobs_lock:
        assert "delete-route-job" not in main_mod._book_generation_jobs
    with Session(engine) as session:
        assert session.exec(select(Book).where(Book.slug == created_slug)).first() is None


def test_create_book_route_can_generate_with_openai_planner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import ai_planner as ai
    from hackster_studio.services import books as bs
    from hackster_studio.services import exports as ex
    from hackster_studio.services import prompts as ps
    from hackster_studio.services import story_maker as sm

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(bs, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ex, "GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(ps, "GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(ps, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sm, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ai, "plan_book_with_openai", lambda **kwargs: _sample_ai_plan(kwargs["page_count"]))

    response = client.post(
        "/books",
        data={
            "title": "Hackster Niko and the AI Button",
            "slug": f"ai_button_{tmp_path.name}",
            "page_count": "5",
            "idea": "Niko helps a tiny terminal learn to ask before deleting files.",
            "characters": "Hackster Niko, Tiny Terminal",
            "objects": "Golden Gear, Blue Crystal",
            "planner_engine": "openai",
        },
        follow_redirects=False,
    )

    created_slug = response.headers["location"].rsplit("/", 1)[-1]
    page_yaml = yaml.safe_load(
        (tmp_path / "books" / created_slug / "pages" / "page_003.yaml").read_text(encoding="utf-8")
    )
    prompts_dir = tmp_path / "generated" / "prompts" / "pages" / created_slug

    assert response.status_code == 303
    assert page_yaml["status"] == "AI planned"
    assert page_yaml["story_text"] == "AI story text for page 3."
    assert len(list(prompts_dir.glob("*.md"))) == 5
    cleanup_book(created_slug)


def test_create_book_route_can_generate_with_dgx_planner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.automation import dgx_services
    from hackster_studio.services import ai_planner as ai
    from hackster_studio.services import books as bs
    from hackster_studio.services import exports as ex
    from hackster_studio.services import prompts as ps
    from hackster_studio.services import story_maker as sm

    monkeypatch.setenv("DGX_LLM_BASE_URL", "http://192.168.68.136:8000/v1")
    monkeypatch.setattr(bs, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ex, "GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(ps, "GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(ps, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sm, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ai, "plan_book_with_dgx", lambda **kwargs: _sample_ai_plan(kwargs["page_count"]))
    monkeypatch.setattr(dgx_services, "prepare_dgx_planner", lambda: True)
    monkeypatch.setattr(dgx_services, "release_dgx_planner_for_images", lambda: True)

    response = client.post(
        "/books",
        data={
            "title": "Hackster Niko and the DGX Button",
            "slug": f"dgx_button_{tmp_path.name}",
            "page_count": "5",
            "idea": "Niko helps a local model plan a careful adventure.",
            "characters": "Hackster Niko, Local Model",
            "objects": "Golden Gear, Blue Crystal",
            "planner_engine": "dgx",
        },
        follow_redirects=False,
    )

    created_slug = response.headers["location"].rsplit("/", 1)[-1]
    page_yaml = yaml.safe_load(
        (tmp_path / "books" / created_slug / "pages" / "page_003.yaml").read_text(encoding="utf-8")
    )

    assert response.status_code == 303
    assert page_yaml["status"] == "AI planned"
    assert page_yaml["story_text"] == "AI story text for page 3."
    cleanup_book(created_slug)


def test_generate_book_from_dgx_brief_manages_vllm_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlmodel import SQLModel, create_engine
    from hackster_studio.automation import dgx_services
    from hackster_studio.services import ai_planner as ai
    from hackster_studio.services import books as bs

    events: list[str] = []
    monkeypatch.setattr(bs, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ai, "plan_book_with_dgx", lambda **kwargs: _sample_ai_plan(kwargs["page_count"]))
    monkeypatch.setattr(dgx_services, "prepare_dgx_planner", lambda: events.append("start"))
    monkeypatch.setattr(dgx_services, "release_dgx_planner_for_images", lambda: events.append("stop"))

    local_engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(local_engine)
    with Session(local_engine) as session:
        book = bs.create_book(session, title="DGX Handoff", slug="dgx_handoff", page_count=3)
        bs.generate_book_from_dgx_brief(
            session,
            book.slug,
            idea="Niko plans with the DGX, then frees memory for images.",
        )

    assert events == ["start", "stop"]


def test_book_generation_page_has_dgx_generation_form(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import books as bs
    from hackster_studio.services import exports as ex
    from hackster_studio.services import prompts as ps
    from hackster_studio.services import story_maker as sm

    monkeypatch.setattr(bs, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ex, "GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(ps, "GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(ps, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sm, "PROJECT_ROOT", tmp_path)
    create_response = client.post(
        "/books",
        data={
            "title": "Hackster Niko and the Planner Test",
            "slug": f"planner_test_{tmp_path.name}",
            "page_count": "4",
            "idea": "Niko plans a tidy test book.",
            "characters": "Hackster Niko, Test Helper",
            "objects": "Golden Gear",
            "generate_book": "1",
        },
        follow_redirects=False,
    )
    slug = create_response.headers["location"].rsplit("/", 1)[-1]

    response = client.get(f"/book-generation?book_slug={slug}")

    assert response.status_code == 200
    assert "Book Generation" in response.text
    assert "Automated Book Run" in response.text
    assert f'action="/books/{slug}/generate-book"' in response.text
    assert "Generate Book Layout With DGX" in response.text
    assert 'data-generation-job-form' in response.text
    assert f'data-book-generation-book-slug="{slug}"' in response.text
    assert 'data-generation-job-submit' in response.text
    assert "Generate Illustrations" in response.text
    assert "Generate Local" not in response.text
    assert "Generate with OpenAI" not in response.text
    assert "Niko plans a tidy test book." in response.text
    assert "Test Helper" in response.text
    cleanup_book(slug)


def test_images_page_has_current_book_gallery_hooks() -> None:
    response = client.get("/generate?book_slug=book01_password_dragon")

    assert response.status_code == 200
    assert "Book Image Library" in response.text
    assert 'id="gen-book-filters"' in response.text
    assert 'data-current-book-slug="book01_password_dragon"' in response.text


def test_book_detail_links_to_book_generation_page() -> None:
    response = client.get("/books/book01_password_dragon")
    assert response.status_code == 200
    assert "Open Book Generation" in response.text
    assert "/book-generation?book_slug=book01_password_dragon" in response.text


def test_character_detail_by_slug_has_lora_training_bench() -> None:
    response = client.get("/characters/by-slug/samurai_splat")

    assert response.status_code == 200
    assert "LoRA Training Bench" in response.text
    assert "Generate Reference Pack" in response.text
    assert "Delete Reference Pack" in response.text
    assert 'name="image_count"' in response.text
    assert 'max="100"' in response.text
    assert "Choose Training Examples" in response.text
    assert 'data-generation-job-kind="character_reference"' in response.text
    assert 'data-generation-job-form' in response.text
    assert "Process Selected Set Now" in response.text
    assert "Select All" in response.text
    assert "Clear Selection" in response.text
    assert "Delete Selected Images" in response.text
    assert "/characters/by-slug/samurai_splat/delete-selected-images" in response.text
    assert "data-character-auto-selection" in response.text
    assert "/project-assets/assets/layers/characters/" in response.text
    assert "Delete Image" in response.text
    assert "/characters/by-slug/samurai_splat/delete-image" in response.text
    assert "Use This LoRA For Samurai Splat" in response.text


def test_character_reference_pack_route_fetch_starts_status_job(monkeypatch: pytest.MonkeyPatch) -> None:
    import hackster_studio.main as main_mod

    captured: dict[str, object] = {}

    def fake_start(book_slug: str, payload: dict[str, object]) -> main_mod.BookGenerationJob:
        captured["book_slug"] = book_slug
        captured["payload"] = payload
        return main_mod.BookGenerationJob(
            job_id="character-reference-job",
            book_slug=book_slug,
            redirect_url=str(payload["redirect_url"]),
            status="queued",
        )

    monkeypatch.setattr(main_mod, "start_book_generation_job", fake_start)

    response = client.post(
        "/characters/by-slug/samurai_splat/generate-reference-pack",
        data={"character_name": "Samurai Splat", "image_count": "24"},
        headers={"X-Requested-With": "fetch"},
    )

    assert response.status_code == 200
    assert response.json()["job_id"] == "character-reference-job"
    assert captured["book_slug"] == "character_samurai_splat"
    assert captured["payload"] == {
        "run_mode": "single_character_reference",
        "character_name": "Samurai Splat",
        "character_slug": "samurai_splat",
        "force": False,
        "image_count": 24,
        "redirect_url": "/characters/by-slug/samurai_splat",
    }


def test_ai_settings_page_renders_and_saves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import ai_planner as ai

    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_TEXT_MODEL", "")
    monkeypatch.setenv("OPENAI_IMAGE_MODEL", "")
    monkeypatch.setenv("DGX_LLM_BASE_URL", "")
    monkeypatch.setenv("DGX_LLM_MODEL", "")
    monkeypatch.setattr(ai, "ENV_FILE", tmp_path / ".env")

    response = client.get("/settings/ai")
    assert response.status_code == 200
    assert "DGX Setup" in response.text
    assert "OpenAI" not in response.text

    save_response = client.post(
        "/settings/ai",
        data={
            "dgx_base_url": "http://192.168.68.136:8000/v1",
            "dgx_text_model": "qwen-dgx-planner",
            "dgx_api_key": "local-key",
        },
    )

    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert save_response.status_code == 200
    assert "DGX settings saved." in save_response.text
    assert "DGX_LLM_BASE_URL=http://192.168.68.136:8000/v1" in env_text
    assert "DGX_LLM_MODEL=qwen-dgx-planner" in env_text


def test_dgx_planner_log_api_returns_log_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.automation import dgx_services

    monkeypatch.setattr(
        dgx_services,
        "read_dgx_planner_log",
        lambda *, lines=80: f"tail lines={lines}\nrequest running",
    )

    response = client.get("/api/dgx/planner-log?lines=12")

    assert response.status_code == 200
    assert response.json() == {
        "available": True,
        "source": "DGX vLLM planner log",
        "log": "tail lines=12\nrequest running",
    }


def test_generate_book_route_fetch_starts_book_generation_job(monkeypatch: pytest.MonkeyPatch) -> None:
    import hackster_studio.main as main_mod

    def fake_openai_settings() -> dict[str, object]:
        return {"api_key_configured": False, "dgx_configured": True}

    def fake_start_book_generation_job(book_slug: str, payload: dict[str, object]) -> main_mod.BookGenerationJob:
        assert book_slug == "book01_password_dragon"
        assert payload["idea"] == "Niko teaches password kindness."
        assert payload["characters"] == "Niko, Byte"
        assert payload["objects"] == "Golden Gear"
        return main_mod.BookGenerationJob(
            job_id="job-test-1",
            book_slug=book_slug,
            redirect_url=f"/books/{book_slug}",
            status="queued",
            stage="queued",
            progress=4,
            events=["Request accepted by Hackster Studio."],
        )

    monkeypatch.setattr(main_mod, "openai_settings", fake_openai_settings)
    monkeypatch.setattr(main_mod, "start_book_generation_job", fake_start_book_generation_job)

    response = client.post(
        "/books/book01_password_dragon/generate-book",
        headers={"X-Requested-With": "fetch"},
        data={
            "planner_engine": "dgx",
            "idea": "Niko teaches password kindness.",
            "characters": "Niko, Byte",
            "objects": "Golden Gear",
            "character_count": "2",
            "object_count": "1",
            "reference_notes": "Keep Niko as a separate layer.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == "job-test-1"
    assert payload["status"] == "queued"
    assert payload["events"] == ["Request accepted by Hackster Studio."]


def test_book_generation_job_status_api_returns_request_events() -> None:
    import hackster_studio.main as main_mod

    job = main_mod.BookGenerationJob(
        job_id="job-status-test",
        book_slug="book01_password_dragon",
        redirect_url="/books/book01_password_dragon",
        status="running",
        stage="story_received",
        progress=62,
        events=[
            "Request accepted by Hackster Studio.",
            "Submitting story/layout request to DGX.",
            "DGX returned a structured book plan. (32 pages in response.)",
        ],
        result={"response_pages": 32},
    )

    with main_mod._book_generation_jobs_lock:
        main_mod._book_generation_jobs[job.job_id] = job
    try:
        response = client.get(f"/api/book-generation/jobs/{job.job_id}")
    finally:
        with main_mod._book_generation_jobs_lock:
            main_mod._book_generation_jobs.pop(job.job_id, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == "job-status-test"
    assert payload["stage"] == "story_received"
    assert payload["progress"] == 62
    assert payload["result"] == {"response_pages": 32}
    assert payload["events"][-1] == "DGX returned a structured book plan. (32 pages in response.)"


def test_book_generation_jobs_api_lists_active_jobs() -> None:
    import hackster_studio.main as main_mod

    job = main_mod.BookGenerationJob(
        job_id="job-list-test",
        book_slug="book01_password_dragon",
        redirect_url="/workflow?book_slug=book01_password_dragon",
        status="running",
        stage="images_generating",
        progress=44,
        events=["Generating page 3 of 32."],
        result={"images_done": 3, "images_total": 32},
    )

    with main_mod._book_generation_jobs_lock:
        main_mod._book_generation_jobs[job.job_id] = job
    try:
        response = client.get("/api/book-generation/jobs")
    finally:
        with main_mod._book_generation_jobs_lock:
            main_mod._book_generation_jobs.pop(job.job_id, None)

    assert response.status_code == 200
    jobs = response.json()["jobs"]
    listed = next(item for item in jobs if item["job_id"] == "job-list-test")
    assert listed["book_slug"] == "book01_password_dragon"
    assert listed["status"] == "running"
    assert listed["stage"] == "images_generating"
    assert listed["result"] == {"images_done": 3, "images_total": 32}


def test_resume_generation_route_starts_resume_job(monkeypatch: pytest.MonkeyPatch) -> None:
    import hackster_studio.main as main_mod

    captured: dict[str, object] = {}

    def fake_start(book_slug: str, payload: dict[str, object]) -> main_mod.BookGenerationJob:
        captured["book_slug"] = book_slug
        captured["payload"] = payload
        return main_mod.BookGenerationJob(
            job_id="resume-job-test",
            book_slug=book_slug,
            redirect_url=f"/workflow?book_slug={book_slug}",
            status="queued",
            events=["Request accepted by Hackster Studio."],
        )

    monkeypatch.setattr(main_mod, "start_book_generation_job", fake_start)
    response = client.post("/books/book01_password_dragon/resume-generation")

    assert response.status_code == 200
    assert response.json()["job_id"] == "resume-job-test"
    assert captured["payload"] == {"run_mode": "resume"}


def test_book_artifact_counts_report_resume_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hackster_studio.main as main_mod
    from hackster_studio.services import artifacts as artifacts_mod

    monkeypatch.setattr(main_mod, "PROJECT_ROOT", tmp_path)
    # Artifact counting now lives in services.artifacts; patch it there too.
    monkeypatch.setattr(artifacts_mod, "PROJECT_ROOT", tmp_path)
    book_root = tmp_path / "books" / "resume_book"
    for directory in ("pages", "prompts", "illustrations", "review"):
        (book_root / directory).mkdir(parents=True)
    (tmp_path / "data" / "generated" / "page_specs" / "resume_book").mkdir(parents=True)
    (tmp_path / "data" / "generated" / "prompts" / "pages" / "resume_book").mkdir(parents=True)

    for page_number in (1, 2, 3):
        (book_root / "pages" / f"page_{page_number:03d}.yaml").write_text("page: ok\n", encoding="utf-8")
        (book_root / "prompts" / f"page_{page_number:03d}.md").write_text("prompt", encoding="utf-8")
    for page_number in (1, 2):
        (tmp_path / "data" / "generated" / "page_specs" / "resume_book" / f"page_{page_number:02d}.yaml").write_text("spec", encoding="utf-8")
    (book_root / "illustrations" / "page_001.png").write_bytes(b"fake")
    (book_root / "review" / "page_001_review.md").write_text("review", encoding="utf-8")

    counts = main_mod._book_artifact_counts("resume_book", 3)

    assert counts["pages"] == 3
    assert counts["book_prompts"] == 3
    assert counts["page_specs"] == 2
    assert counts["images"] == 1
    assert counts["reviews"] == 1


def test_full_generation_artifact_audit_requires_images_and_exports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hackster_studio.main as main_mod
    from hackster_studio import jobs as jobs_mod
    from hackster_studio.services import artifacts as artifacts_mod

    monkeypatch.setattr(main_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(artifacts_mod, "PROJECT_ROOT", tmp_path)
    # The artifact-audit helpers now live in .jobs; patch their globals there.
    monkeypatch.setattr(jobs_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(jobs_mod, "book_page_count", lambda book_slug: 2)
    monkeypatch.setattr(main_mod, "book_page_count", lambda book_slug: 2)
    book_root = tmp_path / "books" / "audit_book"
    for directory in ("pages", "prompts", "illustrations", "review", "exports/lulu", "exports/affinity"):
        (book_root / directory).mkdir(parents=True)
    (tmp_path / "data" / "generated" / "page_specs" / "audit_book").mkdir(parents=True)

    for page_number in (1, 2):
        (book_root / "pages" / f"page_{page_number:03d}.yaml").write_text("page: ok\n", encoding="utf-8")
        (book_root / "prompts" / f"page_{page_number:03d}.md").write_text("prompt\n", encoding="utf-8")
        (book_root / "illustrations" / f"page_{page_number:03d}.png").write_bytes(b"fake")
        (book_root / "review" / f"page_{page_number:03d}_review.md").write_text("review\n", encoding="utf-8")
        (tmp_path / "data" / "generated" / "page_specs" / "audit_book" / f"page_{page_number:02d}.yaml").write_text("spec\n", encoding="utf-8")
    (book_root / "exports" / "lulu" / "audit_book_interior_lulu_print.pdf").write_bytes(b"%PDF")
    (book_root / "exports" / "affinity" / "audit_book_affinity_starter.idml").write_text("idml", encoding="utf-8")

    audit = main_mod._assert_full_book_generation_complete("audit_book")

    assert audit["images"] == 2
    assert audit["reviews"] == 2
    assert audit["production_pdf_exists"] is True
    assert audit["idml_exists"] is True
    assert "2/2 images" in main_mod._artifact_audit_message(audit)


def test_full_generation_artifact_audit_fails_when_missing_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hackster_studio.main as main_mod
    from hackster_studio import jobs as jobs_mod
    from hackster_studio.services import artifacts as artifacts_mod

    monkeypatch.setattr(main_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(artifacts_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(jobs_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(jobs_mod, "book_page_count", lambda book_slug: 2)
    monkeypatch.setattr(main_mod, "book_page_count", lambda book_slug: 2)
    book_root = tmp_path / "books" / "audit_missing_book"
    for directory in ("pages", "prompts", "illustrations", "review"):
        (book_root / directory).mkdir(parents=True)
    (tmp_path / "data" / "generated" / "page_specs" / "audit_missing_book").mkdir(parents=True)
    (book_root / "pages" / "page_001.yaml").write_text("page: ok\n", encoding="utf-8")
    (book_root / "prompts" / "page_001.md").write_text("prompt\n", encoding="utf-8")
    (tmp_path / "data" / "generated" / "page_specs" / "audit_missing_book" / "page_01.yaml").write_text("spec\n", encoding="utf-8")

    with pytest.raises(RuntimeError) as exc_info:
        main_mod._assert_full_book_generation_complete("audit_missing_book")

    message = str(exc_info.value)
    assert "Final artifact check failed" in message
    assert "page images: 0/2" in message
    assert "Lulu production PDF" in message


def test_page_image_artifact_audit_requires_generated_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hackster_studio.main as main_mod
    from hackster_studio import jobs as jobs_mod

    monkeypatch.setattr(main_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(jobs_mod, "PROJECT_ROOT", tmp_path)
    image_dir = tmp_path / "books" / "audit_page_book" / "illustrations"
    image_dir.mkdir(parents=True)

    with pytest.raises(RuntimeError):
        main_mod._assert_page_image_generation_complete("audit_page_book", 3)

    (image_dir / "page_003.png").write_bytes(b"fake")
    audit = main_mod._assert_page_image_generation_complete("audit_page_book", 3)
    assert audit["image_exists"] is True


def test_story_maker_renders_page_regeneration_controls() -> None:
    response = client.get("/story-maker?book_slug=book01_password_dragon&page=4")
    assert response.status_code == 200
    assert 'data-page-regenerate="story"' in response.text
    assert 'data-page-regenerate="prompt"' in response.text
    assert 'data-page-regenerate="image"' in response.text
    assert 'data-page-regenerate="all"' in response.text


def test_regenerate_page_prompt_route_refreshes_selected_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hackster_studio.main as main_mod

    refreshed: list[tuple[str, int]] = []
    monkeypatch.setattr(
        main_mod,
        "_refresh_book_page_prompt_package",
        lambda book_slug, page_number: refreshed.append((book_slug, page_number)),
    )

    response = client.post("/api/books/book01_password_dragon/pages/4/regenerate-prompt")

    assert response.status_code == 200
    payload = response.json()
    assert payload["page_number"] == 4
    assert payload["prompt_path"]
    assert refreshed == [("book01_password_dragon", 4)]


def test_planner_summaries_stay_compact() -> None:
    from hackster_studio.services.books import planner_request_summary, planner_response_summary

    book = SimpleNamespace(
        title="Hackster Niko and the Password Dragon",
        page_count=32,
        target_age="5-8",
        lesson="Strong passwords and careful sharing.",
    )
    request_summary = planner_request_summary(
        book,
        idea="Niko helps a dragon learn passwords. " * 20,
        focus_characters=["Hackster Niko", "Password Dragon"],
        focus_items=["Golden Gear", "Tiny Bug"],
        reference_notes="Use layered Niko art. " * 20,
    )
    plan = {
        "title": "Hackster Niko and the Password Dragon",
        "lesson": "Strong passwords and careful sharing.",
        "summary": "Niko and Dragon learn how to make long, silly, secret passwords.",
        "focus_characters": ["Hackster Niko", "Password Dragon"],
        "focus_items": ["Golden Gear", "Tiny Bug"],
        "pages": [
            {
                "page_number": index,
                "page_type": "story",
                "scene_title": f"Scene {index}",
                "story_text": "This is a polished story moment. " * 8,
            }
            for index in range(1, 6)
        ],
    }

    response_summary = planner_response_summary(plan)

    assert request_summary["page_count"] == 32
    assert request_summary["focus_characters"] == ["Hackster Niko", "Password Dragon"]
    assert len(request_summary["idea"]) < 230
    assert len(request_summary["reference_notes"]) < 190
    assert response_summary["page_count"] == 5
    assert len(response_summary["page_samples"]) == 4
    assert all(len(sample["story"]) <= 120 for sample in response_summary["page_samples"])


def test_prepare_book_review_scenes_links_current_story_and_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hackster_studio.services import story_maker as sm

    book_slug = "fresh_book"
    book_root = tmp_path / "books" / book_slug
    (book_root / "pages").mkdir(parents=True)
    (book_root / "illustrations").mkdir(parents=True)
    (book_root / "pages" / "page_001.yaml").write_text(
        yaml.safe_dump(
            {
                "page_number": 1,
                "page_type": "story",
                "scene_title": "Fresh Scene",
                "story_text": "Fresh dialogue from the generated book.",
                "illustration_direction": "Fresh image direction.",
                "characters": ["Hackster Niko"],
                "environment": "Cyber Forest",
                "emotion": "curious",
                "camera": "wide",
                "hidden_objects": ["Golden Gear"],
                "text_safe_area": "Bottom third.",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (book_root / "illustrations" / "page_001.png").write_bytes(b"fake png")

    monkeypatch.setattr(sm, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path / "storybook_scenes")
    monkeypatch.setattr(sm, "review_niko_layer", lambda page_number: None)

    existing_scene_path = sm.scene_path(book_slug, 1)
    existing_scene_path.parent.mkdir(parents=True)
    existing_scene_path.write_text(
        json.dumps(
            {
                "book_slug": book_slug,
                "page_number": 1,
                "canvas": {
                    "trim_inches": [8.5, 8.5],
                    "bleed_inches": 0.125,
                    "safe_margin_inches": 0.5,
                    "dpi": 300,
                    "width_px": 2625,
                    "height_px": 2625,
                },
                "layers": [
                    sm.review_text_layer("Old text"),
                ],
            }
        ),
        encoding="utf-8",
    )

    result = sm.prepare_book_review_scenes(book_slug)
    scene = sm.load_scene(book_slug, 1)
    text_layer = next(layer for layer in scene["layers"] if layer["id"] == "page_text")
    image_layer = next(layer for layer in scene["layers"] if layer["id"] == "book_illustration")

    assert result["prepared_count"] == 1
    assert result["images_linked"] == 1
    assert scene["scene_title"] == "Fresh Scene"
    assert scene["story_text"] == "Fresh dialogue from the generated book."
    assert scene["status"] == "generated"
    assert text_layer["text"] == "Fresh dialogue from the generated book."
    assert text_layer["transform"]["y"] == 0.82
    assert image_layer["asset_path"] == "books/fresh_book/illustrations/page_001.png"


def test_openai_planner_service_parses_structured_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hackster_studio.services import ai_planner as ai

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    class FakeResponses:
        def create(self, **kwargs: object) -> SimpleNamespace:
            assert kwargs["model"]
            assert "json_schema" in str(kwargs["text"])
            return SimpleNamespace(output_text=json.dumps(_sample_ai_plan(3)))

    client_stub = SimpleNamespace(responses=FakeResponses())
    plan = ai.plan_book_with_openai(
        title="AI Plan",
        idea="Niko fixes a router.",
        lesson="Ask before changing settings.",
        page_count=3,
        target_age="5-8",
        characters=["Hackster Niko"],
        objects=["Golden Gear"],
        reference_notes="",
        client=client_stub,
        model="gpt-test",
    )

    assert len(plan["pages"]) == 3
    assert plan["pages"][0]["story_text"] == "AI story text for page 1."
    assert plan["lesson"] == "AI generated lesson."


def test_dgx_planner_service_uses_bounded_chat_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hackster_studio.services import ai_planner as ai

    monkeypatch.setenv("DGX_LLM_BASE_URL", "http://192.168.68.136:8000/v1")
    monkeypatch.setenv("DGX_LLM_MAX_TOKENS", "2048")

    class FakeResponses:
        def create(self, **kwargs: object) -> SimpleNamespace:
            raise AssertionError("DGX planner should use chat completions directly")

    class FakeChatCompletions:
        def create(self, **kwargs: object) -> SimpleNamespace:
            assert kwargs["model"] == "dgx-test"
            assert kwargs["response_format"] == {"type": "json_object"}
            assert kwargs["temperature"] == 0.1
            assert kwargs["max_tokens"] == 2048
            assert "/no_think" in str(kwargs["messages"])
            message = SimpleNamespace(
                content="<think>\n\n</think>\n\n" + json.dumps(_sample_ai_plan(3))
            )
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    client_stub = SimpleNamespace(
        responses=FakeResponses(),
        chat=SimpleNamespace(completions=FakeChatCompletions()),
    )
    plan = ai.plan_book_with_dgx(
        title="DGX Plan",
        idea="Niko plans locally.",
        lesson="Use local compute wisely.",
        page_count=3,
        target_age="5-8",
        characters=["Hackster Niko"],
        objects=["Golden Gear"],
        reference_notes="",
        client=client_stub,
        model="dgx-test",
    )

    assert len(plan["pages"]) == 3
    assert plan["pages"][2]["scene_title"] == "AI Scene 3"


def test_dgx_planner_invalid_output_error_includes_compact_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hackster_studio.services import ai_planner as ai

    monkeypatch.setenv("DGX_LLM_BASE_URL", "http://192.168.68.136:8000/v1")

    class FakeChatCompletions:
        def create(self, **kwargs: object) -> SimpleNamespace:
            message = SimpleNamespace(
                content=json.dumps(
                    {
                        "title": "Bad Planner Response",
                        "summary": "This is missing pages.",
                        "message": "model stopped early",
                    }
                )
            )
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    client_stub = SimpleNamespace(chat=SimpleNamespace(completions=FakeChatCompletions()))

    with pytest.raises(ValueError) as exc_info:
        ai.plan_book_with_dgx(
            title="Bad Plan",
            idea="Test invalid output.",
            lesson="Debug clearly.",
            page_count=3,
            target_age="5-8",
            characters=["Samurai Splat"],
            objects=["Slippery Scroll"],
            reference_notes="",
            client=client_stub,
            model="dgx-test",
        )

    message = str(exc_info.value)
    assert "expected 3" in message
    assert "Top-level keys" in message
    assert "pages field: NoneType" in message
    assert "Bad Planner Response" in message


def test_dgx_planner_large_books_are_planned_one_page_at_a_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hackster_studio.services import ai_planner as ai

    monkeypatch.setenv("DGX_LLM_BASE_URL", "http://192.168.68.136:8000/v1")
    monkeypatch.setenv("DGX_LLM_DIRECT_PAGE_LIMIT", "8")
    calls: list[str] = []
    saved_pages: list[int] = []

    class FakeChatCompletions:
        def create(self, **kwargs: object) -> SimpleNamespace:
            content = str(kwargs["messages"])
            if "Create only the high-level plan" in content:
                calls.append("overview")
                message = SimpleNamespace(content=json.dumps(_sample_ai_overview(9)))
                return SimpleNamespace(choices=[SimpleNamespace(message=message)])

            match = re.search(r"Write page (\d+) of 9 only", content)
            assert match, content
            page_number = int(match.group(1))
            calls.append(f"page-{page_number}")
            page = _sample_ai_plan(9)["pages"][page_number - 1]
            message = SimpleNamespace(content=json.dumps({"page": page}))
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    client_stub = SimpleNamespace(chat=SimpleNamespace(completions=FakeChatCompletions()))
    plan = ai.plan_book_with_dgx(
        title="Samurai Splat",
        idea="A comic where Samurai Splat goes splat at the end.",
        lesson="Patience and timing.",
        page_count=9,
        target_age="5-8",
        characters=["Samurai Splat", "Shotgun Bob"],
        objects=["Slippery Scroll"],
        reference_notes="No Hackster Niko in this comic.",
        client=client_stub,
        model="dgx-test",
        page_callback=lambda page: saved_pages.append(int(page["page_number"])),
    )

    assert len(plan["pages"]) == 9
    assert calls == ["overview", *(f"page-{page_number}" for page_number in range(1, 10))]
    assert saved_pages == list(range(1, 10))


def _sample_ai_plan(page_count: int) -> dict[str, object]:
    return {
        "title": "AI Generated Hackster Niko Book",
        "lesson": "AI generated lesson.",
        "summary": "A generated test plan.",
        "focus_characters": ["Hackster Niko", "Tiny Terminal"],
        "focus_items": ["Golden Gear", "Blue Crystal"],
        "reference_notes": "Keep Niko consistent.",
        "pages": [
            {
                "page_number": page_number,
                "page_type": "story" if page_number > 1 else "front_matter",
                "scene_title": f"AI Scene {page_number}",
                "story_text": f"AI story text for page {page_number}.",
                "illustration_direction": f"AI illustration direction for page {page_number}; no baked text.",
                "characters": ["Hackster Niko"],
                "environment": "AI Test World",
                "emotion": "curious",
                "camera": "storybook view",
                "hidden_objects": ["Golden Gear"],
                "text_safe_area": "Leave editable text space.",
            }
            for page_number in range(1, page_count + 1)
        ],
    }


def _sample_ai_overview(page_count: int) -> dict[str, object]:
    return {
        "title": "AI Generated Comic",
        "lesson": "AI generated lesson.",
        "summary": "A generated test overview.",
        "focus_characters": ["Samurai Splat", "Shotgun Bob"],
        "focus_items": ["Slippery Scroll"],
        "reference_notes": "Keep the main character consistent.",
        "page_outline": [
            {
                "page_number": page_number,
                "page_type": "story" if page_number > 1 else "front_matter",
                "scene_title": f"AI Scene {page_number}",
                "beat": f"Story beat {page_number}.",
                "characters": ["Samurai Splat"],
                "environment": "dojo courtyard",
            }
            for page_number in range(1, page_count + 1)
        ],
    }


def test_set_current_book_route_sets_cookie() -> None:
    response = client.post("/books/book01_password_dragon/set-current", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/workflow"
    assert "hackster_current_book=book01_password_dragon" in response.headers["set-cookie"]


def test_story_maker_uses_current_book_cookie() -> None:
    response = client.get(
        "/story-maker?page=1",
        cookies={"hackster_current_book": "book01_password_dragon"},
    )
    assert response.status_code == 200
    assert "book01_password_dragon" in response.text


def test_book_page_edit_route_updates_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import books as bs
    from hackster_studio.services import story_maker as sm

    monkeypatch.setattr(bs, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sm, "PROJECT_ROOT", tmp_path)
    create_response = client.post(
        "/books",
        data={"title": "Temporary Route Book", "slug": f"temporary_route_book_{tmp_path.name}", "page_count": "2"},
        follow_redirects=False,
    )
    slug = create_response.headers["location"].rsplit("/", 1)[-1]

    response = client.post(
        f"/books/{slug}/pages/1/edit",
        data={
            "scene_title": "Updated Scene",
            "story_text": "Updated page words.",
            "illustration_direction": "Updated art direction.",
            "status": "drafted",
        },
        follow_redirects=False,
    )

    page_yaml = (tmp_path / "books" / slug / "pages" / "page_001.yaml").read_text(encoding="utf-8")
    assert response.status_code == 303
    assert "Updated page words." in page_yaml
    assert "Updated art direction." in page_yaml
    cleanup_book(slug)

# ── Scene API ─────────────────────────────────────────────────────────────────


def test_get_scene_api_returns_json() -> None:
    response = client.get("/api/scenes/book01_password_dragon/4")
    assert response.status_code == 200
    data = response.json()
    assert data["book_slug"] == "book01_password_dragon"
    assert data["page_number"] == 4
    assert isinstance(data["layers"], list)
    assert "qa" in data


def test_get_scene_qa_api_returns_report() -> None:
    response = client.get("/api/scenes/book01_password_dragon/4/qa")
    assert response.status_code == 200
    data = response.json()
    assert "issues" in data
    assert "errors" in data


def test_book_readiness_api_returns_page_grid() -> None:
    response = client.get("/api/books/book01_password_dragon/readiness")
    assert response.status_code == 200
    data = response.json()
    assert data["page_count"] >= 1
    assert len(data["pages"]) == data["page_count"]


def test_put_scene_status_updates_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import story_maker as sm
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path)

    scene = default_scene("book01_password_dragon", 4)
    save_scene(scene)
    response = client.put(
        "/api/scenes/book01_password_dragon/4/status",
        json={"status": "approved", "approved_by": "test"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "approved"
    assert data["approval"]["approved"] is True


def test_apply_text_style_all_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import story_maker as sm

    monkeypatch.setattr(sm, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path / "scenes")
    monkeypatch.setattr(sm, "LAYERS_DIR", tmp_path / "assets" / "layers")
    pages_dir = tmp_path / "books" / "demo_book" / "pages"
    illustrations_dir = tmp_path / "books" / "demo_book" / "illustrations"
    pages_dir.mkdir(parents=True)
    illustrations_dir.mkdir(parents=True)
    for page_number in (1, 2):
        (pages_dir / f"page_{page_number:03d}.yaml").write_text(f"story_text: Page {page_number}\n", encoding="utf-8")
        (illustrations_dir / f"page_{page_number:03d}.png").write_bytes(b"fake")
    scene = sm.default_scene("demo_book", 1)
    sm.save_scene(scene)

    response = client.post(
        "/api/scenes/demo_book/1/text-style/apply-all",
        json={"layer_id": "page_text"},
    )

    assert response.status_code == 200
    assert response.json()["updated_count"] == 2


def test_get_scene_api_new_book_returns_default() -> None:
    response = client.get("/api/scenes/never_before_seen_book/1")
    assert response.status_code == 200
    data = response.json()
    assert data["book_slug"] == "never_before_seen_book"
    assert data["page_number"] == 1
    assert len(data["layers"]) > 0


def test_get_scene_api_rejects_invalid_slug() -> None:
    response = client.get("/api/scenes/../1")
    assert response.status_code in (404, 422)


def test_put_scene_api_saves_and_reloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import story_maker as sm
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path)

    scene = default_scene("book01_password_dragon", 7)
    scene["lighting_brief"] = "cool_forest_ambient"
    response = client.put("/api/scenes/book01_password_dragon/7", json=scene)

    assert response.status_code == 204
    saved = json.loads((tmp_path / "book01_password_dragon" / "page_007.scene.json").read_text())
    assert saved["lighting_brief"] == "cool_forest_ambient"


def test_put_scene_api_rejects_mismatched_slug() -> None:
    scene = default_scene("book01_password_dragon", 4)
    response = client.put("/api/scenes/wrong_slug/4", json=scene)
    assert response.status_code == 422


def test_put_scene_api_rejects_mismatched_page_number() -> None:
    scene = default_scene("book01_password_dragon", 4)
    response = client.put("/api/scenes/book01_password_dragon/99", json=scene)
    assert response.status_code == 422


def test_put_scene_api_rejects_missing_layers() -> None:
    response = client.put(
        "/api/scenes/book01_password_dragon/4",
        json={"book_slug": "book01_password_dragon", "page_number": 4},
    )
    assert response.status_code == 422


def test_put_scene_api_empty_layers_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import story_maker as sm
    monkeypatch.setattr(sm, "SCENE_ROOT", tmp_path)

    response = client.put(
        "/api/scenes/book01_password_dragon/4",
        json={"book_slug": "book01_password_dragon", "page_number": 4, "layers": []},
    )
    assert response.status_code == 204
