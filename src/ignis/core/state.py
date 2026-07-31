"""Persistent state: installed GitHub apps, API cache, and settings.

Writes are atomic (temp file + rename) and the file is created 0600 because
it may hold a GitHub token. A corrupt file is moved aside, never fatal.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Fallback window size, and the bounds a remembered size must fall within.
DEFAULT_WINDOW_SIZE = (1000, 700)
MIN_WINDOW_DIMENSION = 360
MAX_WINDOW_DIMENSION = 10000


def _sane_dimension(value: Any, fallback: int) -> int:
    """Coerce a stored window dimension to something usable."""
    if not isinstance(value, int) or isinstance(value, bool):
        return fallback
    if not MIN_WINDOW_DIMENSION <= value <= MAX_WINDOW_DIMENSION:
        return fallback
    return value


@dataclass(frozen=True)
class InstalledApp:
    """Record of a GitHub-sourced app installed by Ignis."""

    tag: str
    files: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """Serialise for state.json."""
        return {"tag": self.tag, "files": list(self.files)}


@dataclass(frozen=True)
class CacheEntry:
    """A cached GitHub API response with its ETag."""

    etag: str
    payload: dict[str, Any] = field(default_factory=dict)
    fetched_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        """Serialise for state.json."""
        return {"etag": self.etag, "json": self.payload, "fetched_at": self.fetched_at}


class State:
    """Reads and writes state.json.

    One instance is shared by the UI thread and every worker thread (install
    actions record results, update checks write the API cache, settings and
    window close save from the main loop). The lock keeps a mutation on one
    thread from changing a dict another thread is serialising — without it,
    ``json.dump`` can raise "dictionary changed size during iteration"
    mid-install.
    """

    def __init__(self, path: Path, data: dict[str, Any] | None = None) -> None:
        self.path = path
        self._data: dict[str, Any] = data if data is not None else _empty()
        self._lock = threading.RLock()

    @classmethod
    def load(cls, path: Path) -> State:
        """Load state from ``path``, starting fresh if missing or corrupt."""
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return cls(path)
        except OSError:
            log.warning("could not read state at %s — starting fresh", path,
                        exc_info=True)
            return cls(path)

        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("state root is not an object")
        except (json.JSONDecodeError, ValueError):
            log.warning("state at %s is corrupt — starting fresh", path, exc_info=True)
            _move_aside(path)
            return cls(path)

        return cls(path, _merged(parsed))

    def save(self) -> None:
        """Write state atomically with 0600 permissions. Thread-safe."""
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            )
            temp_path = Path(handle.name)
            try:
                with handle:
                    json.dump(self._data, handle, indent=2, sort_keys=True)
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    temp_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
                except OSError:
                    # Permission bits are a no-op on some filesystems (and Windows).
                    log.debug("could not chmod %s", temp_path, exc_info=True)
                os.replace(temp_path, self.path)
            except OSError:
                log.exception("could not save state to %s", self.path)
                temp_path.unlink(missing_ok=True)
                raise

    # -- installed GitHub apps ------------------------------------------

    def installed(self, app_id: str) -> InstalledApp | None:
        """Record for an installed GitHub app, or None."""
        entry = self._data["github_apps"].get(app_id)
        if not isinstance(entry, dict) or "tag" not in entry:
            return None
        files = entry.get("files")
        return InstalledApp(
            tag=str(entry["tag"]),
            files=tuple(str(f) for f in files) if isinstance(files, list) else (),
        )

    def set_installed(self, app_id: str, record: InstalledApp) -> None:
        """Record an installed GitHub app."""
        with self._lock:
            self._data["github_apps"][app_id] = record.as_dict()

    def clear_installed(self, app_id: str) -> None:
        """Forget an installed GitHub app."""
        with self._lock:
            self._data["github_apps"].pop(app_id, None)

    # -- GitHub API cache -----------------------------------------------

    def cache(self, repo: str) -> CacheEntry | None:
        """Cached release response for ``repo``, or None."""
        entry = self._data["api_cache"].get(repo)
        if not isinstance(entry, dict) or "etag" not in entry:
            return None
        payload = entry.get("json")
        return CacheEntry(
            etag=str(entry["etag"]),
            payload=payload if isinstance(payload, dict) else {},
            fetched_at=str(entry.get("fetched_at", "")),
        )

    def set_cache(self, repo: str, etag: str, payload: dict[str, Any]) -> None:
        """Store a release response with its ETag."""
        with self._lock:
            self._data["api_cache"][repo] = CacheEntry(
                etag=etag,
                payload=payload,
                fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
            ).as_dict()

    # -- per-app settings ------------------------------------------------

    def app_settings(self, app_id: str) -> dict[str, str]:
        """Answers the user gave for this app's setup questions."""
        stored = self._data["app_settings"].get(app_id)
        if not isinstance(stored, dict):
            return {}
        return {str(k): str(v) for k, v in stored.items() if isinstance(v, str)}

    def set_app_settings(self, app_id: str, values: dict[str, str]) -> None:
        """Record the answers for this app.

        Nothing secret is ever stored here — see docs/design-media-host.md.
        Choosing NFS over SMB removed the only password Ignis would have had
        to handle, and this store has no protection suitable for one.
        """
        with self._lock:
            self._data["app_settings"][app_id] = dict(values)

    def clear_app_settings(self, app_id: str) -> None:
        """Forget this app's answers."""
        with self._lock:
            self._data["app_settings"].pop(app_id, None)

    # -- window geometry -------------------------------------------------

    def window_geometry(self) -> tuple[int, int, bool]:
        """Remembered window size and maximised state.

        Values are sanity-checked: a corrupt or absurd size in state.json
        must not produce a window the user cannot see or grab.
        """
        stored = self._data["settings"].get("window")
        if not isinstance(stored, dict):
            return DEFAULT_WINDOW_SIZE + (False,)

        width = _sane_dimension(stored.get("width"), DEFAULT_WINDOW_SIZE[0])
        height = _sane_dimension(stored.get("height"), DEFAULT_WINDOW_SIZE[1])
        return width, height, bool(stored.get("maximized", False))

    def set_window_geometry(self, width: int, height: int, maximized: bool) -> None:
        """Remember the window size for next launch."""
        with self._lock:
            self._data["settings"]["window"] = {
                "width": _sane_dimension(width, DEFAULT_WINDOW_SIZE[0]),
                "height": _sane_dimension(height, DEFAULT_WINDOW_SIZE[1]),
                "maximized": bool(maximized),
            }

    # -- settings --------------------------------------------------------

    @property
    def github_pat(self) -> str:
        """The user's GitHub personal access token (may be empty)."""
        value = self._data["settings"].get("github_pat", "")
        return value if isinstance(value, str) else ""

    @github_pat.setter
    def github_pat(self, value: str) -> None:
        with self._lock:
            self._data["settings"]["github_pat"] = value.strip()


def _empty() -> dict[str, Any]:
    """A blank state document."""
    return {"github_apps": {}, "api_cache": {}, "settings": {}, "app_settings": {}}


def _merged(parsed: dict[str, Any]) -> dict[str, Any]:
    """Fill in any missing top-level sections of a loaded document."""
    data = _empty()
    for key in data:
        value = parsed.get(key)
        if isinstance(value, dict):
            data[key] = value
    return data


def _move_aside(path: Path) -> None:
    """Preserve a corrupt state file for debugging instead of deleting it."""
    try:
        path.replace(path.with_suffix(path.suffix + ".corrupt"))
    except OSError:
        log.debug("could not preserve corrupt state file", exc_info=True)
