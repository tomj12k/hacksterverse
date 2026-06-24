"""Security regression tests for path confinement and input validation.

Each test here pins a fix for a specific finding; a regression that reopens the
hole should turn the corresponding test red.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hackster_studio.main import app

client = TestClient(app)


# ── SEC-1: project_asset must not serve files outside the asset roots ──────────


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "data/hackster_studio.sqlite3",
        "hackster_studio/main.py",
        "configs/dgx_model_profiles.yaml",
        "../etc/passwd",
        "books/../.env",
    ],
)
def test_project_asset_refuses_paths_outside_serve_roots(path: str) -> None:
    resp = client.get(f"/project-assets/{path}", follow_redirects=False)
    # Must never return file contents: 403 (outside roots) or 404 (normalized
    # away) are both acceptable; 200 would mean the file leaked.
    assert resp.status_code in (403, 404), (path, resp.status_code)


# ── SEC-4: character LoRA paths must reject traversal slugs ────────────────────


@pytest.mark.parametrize("slug", ["../../../etc", "..", "a/b", "foo/../bar"])
def test_character_training_rejects_unsafe_slug(slug: str, tmp_path: Path) -> None:
    from hackster_studio.services import character_training as ct

    # The path builder is the chokepoint; it must refuse traversal slugs so no
    # downstream write/glob can escape the characters directory.
    with pytest.raises(ValueError):
        ct._character_root(slug)
    with pytest.raises(ValueError):
        ct.save_training_selection(slug, [])


def test_character_training_accepts_safe_slug() -> None:
    from hackster_studio.services import character_training as ct

    root = ct._character_root("firewall_fox")
    assert root.name == "firewall_fox"


# ── SEC-3: exporter must not read asset_path outside the asset roots ───────────


def test_export_scene_skips_traversal_asset_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PIL import Image

    from hackster_studio.services import exporter as exp
    from hackster_studio.services.story_maker import default_scene

    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setattr(exp, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(exp, "GENERATED_PAGES_DIR", tmp_path / "out")

    # A NON-image secret outside the asset roots. Without confinement,
    # Image.open() on this would raise and crash the export; with confinement
    # the escaping layer is skipped and the export succeeds. This makes the
    # test discriminating — it would fail if the guard were removed.
    secret = tmp_path / "secret.txt"
    secret.write_text("API_KEY=super-secret")

    scene = default_scene("demo", 1)
    for layer in scene["layers"]:
        if layer["type"] == "background":
            layer["asset_path"] = "../secret.txt"

    out = exp.export_scene(scene, mode="flat")
    assert out.exists()
    # Sanity: PIL is importable here (used elsewhere); the point is no crash/read.
    assert Image.open(out).size[0] > 0


# ── SEC-2: print validator route must not read files outside the project ───────


@pytest.mark.parametrize("path", ["/etc/hosts", "/etc/passwd", "~/.ssh/id_rsa"])
def test_print_validator_route_rejects_outside_paths(path: str) -> None:
    resp = client.post("/print-validator", data={"image_path": path})
    assert resp.status_code == 200
    # The confinement message is shown; the host file is never opened/validated.
    assert "inside the project" in resp.text


# ── SEC-5: .env writer must not allow newline injection ────────────────────────


def test_write_env_file_strips_newlines(tmp_path: Path) -> None:
    from hackster_studio.services import ai_planner as ap

    env = tmp_path / ".env"
    ap._write_env_file(env, {"OPENAI_API_KEY": "sk-abc\nDGX_LLM_BASE_URL=http://evil"})
    text = env.read_text()
    # The injected key must not appear on its own line.
    data_lines = [ln for ln in text.splitlines() if "=" in ln and not ln.startswith("#")]
    assert all(not ln.startswith("DGX_LLM_BASE_URL=http://evil") for ln in data_lines)
    assert any(ln.startswith("OPENAI_API_KEY=") for ln in data_lines)


# ── SEC-6: DGX base URL must be a validated http(s) URL ────────────────────────


def test_validated_base_url_accepts_http() -> None:
    from hackster_studio.services.ai_planner import _validated_base_url

    assert _validated_base_url("http://10.0.0.5:8000/v1/") == "http://10.0.0.5:8000/v1"
    assert _validated_base_url("https://api.example.com/v1") == "https://api.example.com/v1"


@pytest.mark.parametrize(
    "bad", ["file:///etc/passwd", "gopher://x", "ftp://h/x", "not a url", "javascript:alert(1)"]
)
def test_validated_base_url_rejects_non_http(bad: str) -> None:
    from hackster_studio.services.ai_planner import _validated_base_url

    with pytest.raises(ValueError):
        _validated_base_url(bad)


# ── SEC-8: CSRF origin guard on state-changing requests ────────────────────────


def test_csrf_blocks_cross_site_origin() -> None:
    resp = client.post(
        "/print-validator",
        data={"image_path": "books/x/y.png"},
        headers={"Origin": "http://evil.example.com"},
    )
    assert resp.status_code == 403
    assert "origin mismatch" in resp.text.lower()


def test_csrf_allows_same_origin() -> None:
    # TestClient default host is "testserver"; a matching Origin is allowed.
    resp = client.post(
        "/print-validator",
        data={"image_path": "books/x/y.png"},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200


def test_csrf_allows_missing_origin() -> None:
    # No Origin header (API client / server-to-server) is not browser CSRF.
    resp = client.post("/print-validator", data={"image_path": "books/x/y.png"})
    assert resp.status_code == 200
