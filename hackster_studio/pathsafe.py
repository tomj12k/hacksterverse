"""Centralized filesystem path-safety helpers.

Every place that serves, opens, writes, or deletes a path derived from
untrusted input (HTTP path/query params, scene JSON, form fields) should route
through here, so confinement logic lives in one audited place instead of being
re-implemented per call site.

Semantics: ``is_within`` means *strictly nested under* a root. A path equal to
a root is NOT considered within it — this prevents a traversal that resolves
back to a root directory (e.g. ``books/..`` -> PROJECT_ROOT) from being treated
as safe and, for example, deleted.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

# Slug grammar shared with services.story_maker._BOOK_SLUG_RE: a leading
# alphanumeric followed by alphanumerics, underscores, or hyphens. This
# excludes path separators, dots, and "..", so a validated slug can never
# traverse out of its intended parent directory.
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def is_within(path: str | Path, root: str | Path) -> bool:
    """Return True if resolved ``path`` is strictly nested under ``root``.

    A path equal to ``root`` returns False by design.

    :param path: candidate path (may be relative or absolute, may not exist)
    :param root: directory the path must live under
    :rtype: bool
    """
    resolved = Path(path).resolve()
    root_resolved = Path(root).resolve()
    return root_resolved in resolved.parents


def is_within_any(path: str | Path, roots: Iterable[str | Path]) -> bool:
    """Return True if ``path`` is strictly nested under any of ``roots``."""
    return any(is_within(path, root) for root in roots)


def resolve_within(candidate: str | Path, roots: Iterable[str | Path]) -> Path:
    """Resolve ``candidate`` and return it only if confined to one of ``roots``.

    :raises ValueError: if the resolved path escapes every allowed root.
    :rtype: Path
    """
    resolved = Path(candidate).resolve()
    if not is_within_any(resolved, roots):
        raise ValueError(f"Path escapes allowed roots: {candidate!r}")
    return resolved


def is_safe_slug(slug: object) -> bool:
    """Return True if ``slug`` matches the safe slug grammar (no traversal)."""
    return bool(_SLUG_RE.fullmatch(str(slug)))


def require_safe_slug(slug: object) -> str:
    """Return ``slug`` unchanged if safe, else raise.

    :raises ValueError: if the slug contains path separators, dots, or other
        characters that could enable directory traversal.
    :rtype: str
    """
    text = str(slug)
    if not is_safe_slug(text):
        raise ValueError(f"Unsafe slug: {slug!r}")
    return text
