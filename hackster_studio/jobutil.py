"""Small utilities for the in-memory job stores.

The generation job dictionaries are process-local and ephemeral. Without
bounding they grow for the lifetime of the server (one entry per generation
ever started). ``evict_oldest`` keeps them capped by dropping the
oldest-inserted entries — Python dicts preserve insertion order, so the first
key is always the oldest.
"""

from __future__ import annotations

from typing import TypeVar

# Maximum number of generation jobs retained in memory per store. Old jobs are
# terminal (done/failed) and only kept for the UI history poll, so a few
# hundred is ample.
MAX_TRACKED_JOBS = 200

_K = TypeVar("_K")
_V = TypeVar("_V")


def evict_oldest(store: dict[_K, _V], max_items: int = MAX_TRACKED_JOBS) -> None:
    """Drop oldest-inserted entries until ``store`` holds at most ``max_items``.

    Callers holding a lock for ``store`` should call this within that lock.

    :param store: insertion-ordered dict to trim in place.
    :param max_items: maximum number of entries to retain.
    """
    while len(store) > max_items:
        del store[next(iter(store))]
