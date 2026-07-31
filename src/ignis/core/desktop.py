"""Building and reading freedesktop .desktop entries."""

from __future__ import annotations

import re
import shlex
from collections.abc import Sequence

from ignis.core.catalog import Category

#: Placeholders the desktop spec allows in Exec, which are not real arguments.
FIELD_CODES = re.compile(r"%[fFuUdDnNickvm]")

#: Freedesktop menu categories per catalog category.
DESKTOP_CATEGORIES = {
    Category.GAMING: "Game;",
    Category.EMULATION: "Game;Emulator;",
    Category.MEDIA: "AudioVideo;",
    Category.STREAMING: "AudioVideo;",
    Category.SYSTEM: "System;",
}


def categories_for(category: Category) -> str:
    """The menu categories an app of this kind belongs in."""
    return DESKTOP_CATEGORIES.get(category, "Utility;")


def quote_exec(parts: Sequence[str]) -> str:
    """Join argv into an Exec= value.

    Every part is quoted: the desktop spec allows double quotes around any
    argument, and quoting unconditionally avoids having to reason about
    which characters need escaping. Note the spec permits only double
    quotes, so shlex.join (which prefers single quotes) must not be used.
    """
    quoted = []
    for part in parts:
        escaped = str(part).replace("\\", "\\\\").replace('"', '\\"')
        quoted.append(f'"{escaped}"')
    return " ".join(quoted)


def parse_exec(entry_text: str) -> list[str] | None:
    """The argv an entry's Exec= line runs, or None if it has none."""
    for line in entry_text.splitlines():
        if not line.startswith("Exec="):
            continue
        value = FIELD_CODES.sub("", line[len("Exec=") :]).strip()
        if not value:
            return None
        try:
            argv = shlex.split(value)
        except ValueError:
            return None
        return argv or None
    return None


def build_entry(
    *,
    name: str,
    comment: str,
    exec_argv: Sequence[str],
    icon: str,
    categories: str,
    app_id: str,
    working_directory: str | None = None,
) -> str:
    """Assemble a .desktop file.

    ``app_id`` is recorded as X-Ignis-App so Ignis can recognise entries it
    created and never touch anyone else's.
    """
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={name}",
        f"Comment={comment}",
        f"Exec={quote_exec(exec_argv)}",
    ]
    if working_directory:
        lines.append(f"Path={working_directory}")
    lines += [
        f"Icon={icon}",
        "Terminal=false",
        f"Categories={categories}",
        f"X-Ignis-App={app_id}",
        "",
    ]
    return "\n".join(lines)


def entry_app_id(entry_text: str) -> str | None:
    """The X-Ignis-App value of an entry, or None if Ignis didn't write it."""
    for line in entry_text.splitlines():
        if line.startswith("X-Ignis-App="):
            return line[len("X-Ignis-App=") :].strip() or None
    return None
