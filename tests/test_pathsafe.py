"""Tests for the centralized path-safety helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from hackster_studio.pathsafe import (
    is_safe_slug,
    is_within,
    is_within_any,
    require_safe_slug,
    resolve_within,
)


def test_is_within_strictly_nested(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    assert is_within(root / "sub" / "f.png", root)
    assert is_within(root / "deep" / "a" / "b.png", root)


def test_is_within_rejects_root_equality(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    # A path equal to the root is NOT within it (prevents books/.. -> root).
    assert not is_within(root, root)


def test_is_within_rejects_traversal(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("x")
    assert not is_within(root / ".." / "secret.txt", root)
    assert not is_within(tmp_path / "secret.txt", root)


def test_is_within_any(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert is_within_any(b / "x.png", [a, b])
    assert not is_within_any(tmp_path / "x.png", [a, b])


def test_resolve_within_ok(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    out = resolve_within(root / "x.png", [root])
    assert out == (root / "x.png").resolve()


def test_resolve_within_raises_on_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ValueError):
        resolve_within(root / ".." / ".." / "etc" / "passwd", [root])
    with pytest.raises(ValueError):
        resolve_within("/etc/passwd", [root])


@pytest.mark.parametrize("slug", ["book01_password_dragon", "niko", "a-b_c", "X1"])
def test_is_safe_slug_accepts(slug: str) -> None:
    assert is_safe_slug(slug)
    assert require_safe_slug(slug) == slug


@pytest.mark.parametrize(
    "slug",
    ["../etc", "a/b", "..", ".", "", "a/../b", "foo/..", "with space", "/abs", "a\\b"],
)
def test_is_safe_slug_rejects(slug: str) -> None:
    assert not is_safe_slug(slug)
    with pytest.raises(ValueError):
        require_safe_slug(slug)
