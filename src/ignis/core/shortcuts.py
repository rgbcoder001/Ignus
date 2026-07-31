"""Desktop shortcuts for installed apps.

Ignis only ever creates, inspects or deletes files it wrote itself, which it
recognises by the X-Ignis-App key inside them (CLAUDE.md hard rule 6).
"""

from __future__ import annotations

import logging
import os
import stat
import tempfile
from pathlib import Path

from ignis.core.desktop import entry_app_id
from ignis.core.host import CommandError, HostBridge

log = logging.getLogger(__name__)

SHORTCUT_PREFIX = "ignis-"


def desktop_dir(bridge: HostBridge) -> Path:
    """The user's desktop folder.

    Asks the host rather than assuming ~/Desktop: the folder is localised,
    and can be relocated or disabled entirely in user-dirs.dirs.
    """
    result = bridge.run(["xdg-user-dir", "DESKTOP"], timeout=15, check=False)
    if result.ok:
        for line in result.output.splitlines():
            candidate = Path(line.strip())
            if candidate.is_absolute():
                return candidate
    log.info("could not resolve the desktop folder — assuming ~/Desktop")
    return Path.home() / "Desktop"


def shortcut_path(directory: Path, app_id: str) -> Path:
    """Where this app's shortcut lives."""
    return directory / f"{SHORTCUT_PREFIX}{app_id}.desktop"


def has_shortcut(directory: Path, app_id: str) -> bool:
    """True if Ignis has already put a shortcut for this app on the desktop."""
    return shortcut_path(directory, app_id).is_file()


def create_shortcut(
    directory: Path, app_id: str, entry_text: str, bridge: HostBridge
) -> Path:
    """Write a desktop shortcut, marked executable and trusted."""
    directory.mkdir(parents=True, exist_ok=True)
    path = shortcut_path(directory, app_id)

    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=directory, prefix=f".{path.name}.",
        suffix=".tmp", delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(entry_text)
        temp_path.chmod(temp_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        os.replace(temp_path, path)
    except OSError:
        temp_path.unlink(missing_ok=True)
        raise

    _mark_trusted(path, bridge)
    log.info("created desktop shortcut %s", path)
    return path


def remove_shortcut(directory: Path, app_id: str) -> None:
    """Delete a shortcut, but only one Ignis created for this app."""
    path = shortcut_path(directory, app_id)
    if not path.is_file():
        return
    try:
        owner = entry_app_id(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        log.warning("could not read %s — leaving it alone", path, exc_info=True)
        return

    if owner != app_id:
        # Someone else's file that happens to sit at this name: never ours to
        # delete.
        log.error("refusing to delete %s — not written by Ignis for %s", path, app_id)
        return

    try:
        path.unlink()
    except OSError:
        log.warning("could not delete %s", path, exc_info=True)


def _mark_trusted(path: Path, bridge: HostBridge) -> None:
    """Ask the desktop to treat the launcher as trusted.

    GNOME hides untrusted launchers; KDE only needs the executable bit,
    which is already set. Best effort — a failure just means the icon may
    need one manual "Allow Launching".
    """
    try:
        bridge.spawn(
            ["gio", "set", "-t", "string", str(path), "metadata::trusted", "true"]
        )
    except CommandError:
        log.info("could not mark %s trusted", path, exc_info=True)
