"""Tests for the asset library scanning service and API endpoints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hackster_studio.main import app
from hackster_studio.services.assets import _relative_paths, list_assets, list_poses

client = TestClient(app)


# ── _relative_paths ───────────────────────────────────────────────────────────


def test_relative_paths_nonexistent_dir_returns_empty(tmp_path: Path) -> None:
    result = _relative_paths(tmp_path / "does_not_exist")
    assert result == []


def test_relative_paths_empty_dir_returns_empty(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    result = _relative_paths(tmp_path / "empty")
    assert result == []


def test_relative_paths_finds_pngs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import assets as assets_mod
    monkeypatch.setattr(assets_mod, "PROJECT_ROOT", tmp_path)
    d = tmp_path / "some_dir"
    d.mkdir()
    (d / "a.png").write_bytes(b"")
    (d / "b.png").write_bytes(b"")

    result = _relative_paths(d)
    assert len(result) == 2
    assert all(r.endswith(".png") for r in result)


def test_relative_paths_ignores_non_png_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import assets as assets_mod
    monkeypatch.setattr(assets_mod, "PROJECT_ROOT", tmp_path)
    d = tmp_path / "dir"
    d.mkdir()
    (d / "image.png").write_bytes(b"")
    (d / "doc.pdf").write_bytes(b"")
    (d / "poses.json").write_bytes(b"")
    (d / "image.jpg").write_bytes(b"")

    result = _relative_paths(d)
    assert len(result) == 1
    assert "image.png" in result[0]


def test_relative_paths_finds_nested_pngs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import assets as assets_mod
    monkeypatch.setattr(assets_mod, "PROJECT_ROOT", tmp_path)
    d = tmp_path / "chars"
    (d / "niko").mkdir(parents=True)
    (d / "niko" / "standing.png").write_bytes(b"")
    (d / "niko" / "waving.png").write_bytes(b"")

    result = _relative_paths(d)
    assert len(result) == 2


def test_relative_paths_returns_sorted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import assets as assets_mod
    monkeypatch.setattr(assets_mod, "PROJECT_ROOT", tmp_path)
    d = tmp_path / "dir"
    d.mkdir()
    (d / "z_last.png").write_bytes(b"")
    (d / "a_first.png").write_bytes(b"")
    (d / "m_middle.png").write_bytes(b"")

    result = _relative_paths(d)
    assert result == sorted(result)


def test_relative_paths_are_posix_strings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import assets as assets_mod
    monkeypatch.setattr(assets_mod, "PROJECT_ROOT", tmp_path)
    d = tmp_path / "dir"
    d.mkdir()
    (d / "img.png").write_bytes(b"")

    result = _relative_paths(d)
    assert all("/" in r or "\\" not in r for r in result)


# ── list_assets ───────────────────────────────────────────────────────────────


def test_list_assets_returns_expected_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import assets as assets_mod
    monkeypatch.setattr(assets_mod, "LAYERS_DIR", tmp_path)
    monkeypatch.setattr(assets_mod, "GENERATED_PAGES_DIR", tmp_path / "generated")

    result = list_assets()
    assert "backgrounds" in result
    assert "midground" in result
    assert "foreground" in result
    assert "characters" in result
    assert "props" in result
    assert "hidden_objects" in result
    assert "generated" in result
    assert "book_illustrations" in result
    assert "book_image_library" in result


def test_list_assets_finds_background_pngs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import assets as assets_mod
    monkeypatch.setattr(assets_mod, "LAYERS_DIR", tmp_path)
    monkeypatch.setattr(assets_mod, "GENERATED_PAGES_DIR", tmp_path / "gen")
    monkeypatch.setattr(assets_mod, "PROJECT_ROOT", tmp_path.parent)
    bg_dir = tmp_path / "backgrounds"
    bg_dir.mkdir()
    (bg_dir / "cyber_forest_ambient_soft.png").write_bytes(b"")

    result = list_assets()
    assert len(result["backgrounds"]) == 1
    assert "cyber_forest_ambient_soft.png" in result["backgrounds"][0]


def test_list_assets_empty_dirs_return_empty_lists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import assets as assets_mod
    monkeypatch.setattr(assets_mod, "LAYERS_DIR", tmp_path)
    monkeypatch.setattr(assets_mod, "GENERATED_PAGES_DIR", tmp_path / "gen")

    result = list_assets()
    assert result["backgrounds"] == []
    assert result["midground"] == []
    assert result["props"] == []


def test_list_assets_characters_grouped_by_slug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import assets as assets_mod
    monkeypatch.setattr(assets_mod, "LAYERS_DIR", tmp_path)
    monkeypatch.setattr(assets_mod, "GENERATED_PAGES_DIR", tmp_path / "gen")
    monkeypatch.setattr(assets_mod, "PROJECT_ROOT", tmp_path.parent)
    (tmp_path / "characters" / "niko").mkdir(parents=True)
    (tmp_path / "characters" / "zara").mkdir(parents=True)
    (tmp_path / "characters" / "niko" / "standing.png").write_bytes(b"")
    (tmp_path / "characters" / "zara" / "waving.png").write_bytes(b"")

    result = list_assets()
    assert "niko" in result["characters"]
    assert "zara" in result["characters"]
    assert len(result["characters"]["niko"]) == 1
    assert len(result["characters"]["zara"]) == 1


def test_list_assets_characters_no_char_dirs_returns_empty_dict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import assets as assets_mod
    monkeypatch.setattr(assets_mod, "LAYERS_DIR", tmp_path)
    monkeypatch.setattr(assets_mod, "GENERATED_PAGES_DIR", tmp_path / "gen")

    result = list_assets()
    assert result["characters"] == {}


def test_list_assets_scans_generated_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import assets as assets_mod
    gen_dir = tmp_path / "pages"
    gen_dir.mkdir(parents=True)
    (gen_dir / "page_001_flat.png").write_bytes(b"")
    (gen_dir / "page_002_draft.png").write_bytes(b"")
    monkeypatch.setattr(assets_mod, "LAYERS_DIR", tmp_path / "layers")
    monkeypatch.setattr(assets_mod, "GENERATED_PAGES_DIR", gen_dir)
    monkeypatch.setattr(assets_mod, "PROJECT_ROOT", tmp_path.parent)

    result = list_assets()
    assert len(result["generated"]) == 2


def test_list_assets_groups_book_illustrations_by_book(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import assets as assets_mod

    book_root = tmp_path / "books" / "samurai_splat_01"
    illustrations = book_root / "illustrations"
    illustrations.mkdir(parents=True)
    (book_root / "book.yaml").write_text("title: Samurai Splat\n", encoding="utf-8")
    (illustrations / "page_001.png").write_bytes(b"")
    (illustrations / "page_002.png").write_bytes(b"")
    monkeypatch.setattr(assets_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(assets_mod, "LAYERS_DIR", tmp_path / "assets" / "layers")
    monkeypatch.setattr(assets_mod, "GENERATED_PAGES_DIR", tmp_path / "data" / "generated" / "pages")

    result = list_assets()

    assert result["book_illustrations"] == [
        {
            "slug": "samurai_splat_01",
            "title": "Samurai Splat",
            "count": 2,
            "images": [
                "books/samurai_splat_01/illustrations/page_001.png",
                "books/samurai_splat_01/illustrations/page_002.png",
            ],
        }
    ]


def test_list_assets_groups_book_image_library_by_book_and_category(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import assets as assets_mod

    book_root = tmp_path / "books" / "samurai_splat_01"
    (book_root / "illustrations").mkdir(parents=True)
    (book_root / "reports" / "render").mkdir(parents=True)
    (book_root / "book.yaml").write_text("title: Samurai Splat\n", encoding="utf-8")
    (book_root / "illustrations" / "page_001.png").write_bytes(b"")
    (book_root / "reports" / "render" / "page-01.jpg").write_bytes(b"")
    text_dir = tmp_path / "assets" / "layers" / "text" / "samurai_splat_01"
    text_dir.mkdir(parents=True)
    (text_dir / "page_001_title.png").write_bytes(b"")
    character_dir = tmp_path / "assets" / "layers" / "characters" / "splat" / "custom"
    character_dir.mkdir(parents=True)
    (character_dir / "samurai_splat_01_page_001_splat.png").write_bytes(b"")

    monkeypatch.setattr(assets_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(assets_mod, "LAYERS_DIR", tmp_path / "assets" / "layers")
    monkeypatch.setattr(assets_mod, "GENERATED_PAGES_DIR", tmp_path / "data" / "generated" / "pages")

    library = list_assets()["book_image_library"]

    assert len(library) == 1
    assert library[0]["slug"] == "samurai_splat_01"
    assert library[0]["count"] == 4
    categories = {category["id"]: category for category in library[0]["categories"]}
    assert categories["illustrations"]["images"] == ["books/samurai_splat_01/illustrations/page_001.png"]
    assert categories["reports"]["images"] == ["books/samurai_splat_01/reports/render/page-01.jpg"]
    assert categories["characters"]["images"] == [
        "assets/layers/characters/splat/custom/samurai_splat_01_page_001_splat.png"
    ]
    assert categories["text"]["images"] == ["assets/layers/text/samurai_splat_01/page_001_title.png"]


def test_list_assets_generated_empty_when_no_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import assets as assets_mod
    monkeypatch.setattr(assets_mod, "LAYERS_DIR", tmp_path)
    monkeypatch.setattr(assets_mod, "GENERATED_PAGES_DIR", tmp_path / "nonexistent_gen")

    result = list_assets()
    assert result["generated"] == []


def test_list_assets_hidden_objects_under_props(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import assets as assets_mod
    monkeypatch.setattr(assets_mod, "LAYERS_DIR", tmp_path)
    monkeypatch.setattr(assets_mod, "GENERATED_PAGES_DIR", tmp_path / "gen")
    monkeypatch.setattr(assets_mod, "PROJECT_ROOT", tmp_path.parent)
    ho_dir = tmp_path / "hidden_objects"
    ho_dir.mkdir()
    (ho_dir / "key.png").write_bytes(b"")

    result = list_assets()
    assert len(result["hidden_objects"]) == 1


# ── list_poses ────────────────────────────────────────────────────────────────


def test_list_poses_reads_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hackster_studio.services import assets as assets_mod
    monkeypatch.setattr(assets_mod, "LAYERS_DIR", tmp_path)
    niko_dir = tmp_path / "characters" / "niko"
    niko_dir.mkdir(parents=True)
    manifest = {
        "character": "niko",
        "poses": [{"id": "waving", "label": "Waving", "tags": ["greeting"]}],
    }
    (niko_dir / "poses.json").write_text(json.dumps(manifest), encoding="utf-8")

    poses = list_poses("niko")
    assert len(poses) == 1
    assert poses[0]["id"] == "waving"
    assert poses[0]["label"] == "Waving"


def test_list_poses_returns_empty_when_no_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import assets as assets_mod
    monkeypatch.setattr(assets_mod, "LAYERS_DIR", tmp_path)

    assert list_poses("unknown_character") == []


def test_list_poses_returns_empty_when_poses_key_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import assets as assets_mod
    monkeypatch.setattr(assets_mod, "LAYERS_DIR", tmp_path)
    niko_dir = tmp_path / "characters" / "niko"
    niko_dir.mkdir(parents=True)
    (niko_dir / "poses.json").write_text(json.dumps({"character": "niko"}), encoding="utf-8")

    assert list_poses("niko") == []


def test_list_poses_empty_poses_array(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import assets as assets_mod
    monkeypatch.setattr(assets_mod, "LAYERS_DIR", tmp_path)
    niko_dir = tmp_path / "characters" / "niko"
    niko_dir.mkdir(parents=True)
    (niko_dir / "poses.json").write_text(
        json.dumps({"character": "niko", "poses": []}), encoding="utf-8"
    )

    assert list_poses("niko") == []


def test_list_poses_malformed_json_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import assets as assets_mod
    monkeypatch.setattr(assets_mod, "LAYERS_DIR", tmp_path)
    niko_dir = tmp_path / "characters" / "niko"
    niko_dir.mkdir(parents=True)
    (niko_dir / "poses.json").write_text("{bad json!!!", encoding="utf-8")

    # Should gracefully return [] instead of raising JSONDecodeError
    assert list_poses("niko") == []


def test_list_poses_returns_multiple_poses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hackster_studio.services import assets as assets_mod
    monkeypatch.setattr(assets_mod, "LAYERS_DIR", tmp_path)
    niko_dir = tmp_path / "characters" / "niko"
    niko_dir.mkdir(parents=True)
    manifest = {
        "character": "niko",
        "poses": [
            {"id": "standing_neutral", "label": "Standing"},
            {"id": "waving", "label": "Waving"},
            {"id": "thinking", "label": "Thinking"},
        ],
    }
    (niko_dir / "poses.json").write_text(json.dumps(manifest), encoding="utf-8")

    poses = list_poses("niko")
    assert len(poses) == 3
    ids = {p["id"] for p in poses}
    assert ids == {"standing_neutral", "waving", "thinking"}


# ── Assets API endpoints ──────────────────────────────────────────────────────


def test_assets_endpoint_returns_200() -> None:
    response = client.get("/api/assets")
    assert response.status_code == 200


def test_assets_endpoint_has_all_keys() -> None:
    data = client.get("/api/assets").json()
    for key in ("backgrounds", "midground", "foreground", "characters", "props", "text", "generated", "book_image_library"):
        assert key in data, f"Missing key: {key}"


def test_assets_endpoint_backgrounds_is_list() -> None:
    data = client.get("/api/assets").json()
    assert isinstance(data["backgrounds"], list)


def test_assets_endpoint_characters_is_dict() -> None:
    data = client.get("/api/assets").json()
    assert isinstance(data["characters"], dict)


def test_poses_endpoint_niko_returns_list() -> None:
    response = client.get("/api/assets/characters/niko/poses")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_poses_endpoint_niko_has_id_and_label() -> None:
    poses = client.get("/api/assets/characters/niko/poses").json()
    if poses:
        assert "id" in poses[0]
        assert "label" in poses[0]


def test_poses_endpoint_unknown_character_returns_empty_list() -> None:
    response = client.get("/api/assets/characters/nonexistent_char/poses")
    assert response.status_code == 200
    assert response.json() == []
