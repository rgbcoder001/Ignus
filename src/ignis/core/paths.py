"""Filesystem locations for bundled data and user files.

Resolves correctly both when packaged as a Flatpak (data under
``/app/share/ignis``) and when running from a source checkout.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_DIR_NAME = "ignis"

# Where the Flatpak build installs the catalog, icons and scripts.
INSTALLED_DATA_DIR = Path("/app/share/ignis")

# paths.py -> core -> ignis -> src -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]


def data_dir() -> Path:
    """Directory holding bundled data (catalog, icons, scripts)."""
    override = os.environ.get("IGNIS_DATA_DIR")
    if override:
        return Path(override)
    if INSTALLED_DATA_DIR.is_dir():
        return INSTALLED_DATA_DIR
    return _REPO_ROOT / "data"


def catalog_path() -> Path:
    """Path to catalog.toml."""
    return data_dir() / "catalog.toml"


def icons_dir() -> Path:
    """Directory holding catalog app icons."""
    return data_dir() / "icons"


def scripts_dir() -> Path:
    """Directory holding vetted shell scripts used by ``script`` sources."""
    installed = INSTALLED_DATA_DIR / "scripts"
    if installed.is_dir():
        return installed
    return _REPO_ROOT / "scripts"


def _xdg_dir(env_var: str, fallback: str) -> Path:
    """Resolve an XDG base directory.

    Flatpak sets XDG_CONFIG_HOME/XDG_STATE_HOME to the app's private
    ~/.var/app/<id>/ locations, so honouring the environment gives the same
    answer as GLib.get_user_config_dir() without importing gi here.
    """
    value = os.environ.get(env_var)
    if value:
        return Path(value)
    return Path.home().joinpath(*fallback.split("/"))


def config_dir() -> Path:
    """Directory for user configuration and state.json."""
    return _xdg_dir("XDG_CONFIG_HOME", ".config") / APP_DIR_NAME


def state_file() -> Path:
    """Path to the persistent state/settings file."""
    return config_dir() / "state.json"


def log_dir() -> Path:
    """Directory for log files."""
    return _xdg_dir("XDG_STATE_HOME", ".local/state") / APP_DIR_NAME


def log_file() -> Path:
    """Path to the rotating log file."""
    return log_dir() / "ignis.log"


def applications_dir() -> Path:
    """Where GitHub-sourced applications are installed."""
    return Path.home() / "Applications"


def desktop_entries_dir() -> Path:
    """Where .desktop launchers for GitHub-sourced apps are written.

    Deliberately NOT XDG_DATA_HOME: inside the sandbox that points at the
    app's private ~/.var/app/<id>/data, where the desktop menu would never
    see the launcher. The manifest grants xdg-data/applications, which the
    host exposes at its real path under $HOME.
    """
    return Path.home() / ".local" / "share" / "applications"


def user_icons_dir() -> Path:
    """Where icons for GitHub-sourced apps are written.

    Real user path rather than XDG_DATA_HOME — see desktop_entries_dir().
    """
    return Path.home() / ".local" / "share" / "icons"


def ensure_dir(path: Path) -> Path:
    """Create ``path`` (and parents) if missing, returning it."""
    path.mkdir(parents=True, exist_ok=True)
    return path
