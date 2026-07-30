"""Comparing release tags against the running version."""

from __future__ import annotations

import re

_SEPARATORS = re.compile(r"[.\-+_]")


def parse_version(text: str) -> tuple[int, ...]:
    """Turn ``v1.2.3`` into ``(1, 2, 3)``.

    Stops at the first non-numeric part, so ``1.2.0-beta1`` compares as
    ``(1, 2, 0)`` — good enough to answer "is there something newer", and it
    never raises on a tag that doesn't look like a version at all.
    """
    parts: list[int] = []
    for chunk in _SEPARATORS.split(text.strip().lstrip("vV")):
        if not chunk.isdigit():
            break
        parts.append(int(chunk))
    return tuple(parts)


def is_newer(candidate: str, current: str) -> bool:
    """True if ``candidate`` is a strictly newer version than ``current``.

    Returns False when either side is unparseable: an unknown tag format
    must never trigger a spurious "update available".
    """
    new = parse_version(candidate)
    old = parse_version(current)
    if not new or not old:
        return False
    return new > old
