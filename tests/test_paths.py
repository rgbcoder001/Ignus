"""Path resolution for bundled data and user directories."""

from __future__ import annotations

from pathlib import Path

from ignis.core import paths


def test_data_dir_falls_back_to_the_repo_checkout(monkeypatch):
    monkeypatch.delenv("IGNIS_DATA_DIR", raising=False)
    assert paths.catalog_path().is_file()


def test_data_dir_honours_the_override(monkeypatch, tmp_path):
    monkeypatch.setenv("IGNIS_DATA_DIR", str(tmp_path))
    assert paths.data_dir() == tmp_path
    assert paths.catalog_path() == tmp_path / "catalog.toml"


def test_config_dir_follows_xdg(monkeypatch, tmp_path):
    """Flatpak redirects XDG_CONFIG_HOME into the app's private dir."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert paths.config_dir() == tmp_path / "cfg" / "ignis"
    assert paths.state_file() == tmp_path / "cfg" / "ignis" / "state.json"


def test_config_dir_falls_back_to_home(monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert paths.config_dir() == Path.home() / ".config" / "ignis"


def test_log_file_follows_xdg_state(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert paths.log_file() == tmp_path / "ignis" / "ignis.log"


def test_desktop_entries_ignore_xdg_data_home(monkeypatch, tmp_path):
    """Launchers must land in the real user dir, not the sandbox's private one.

    Flatpak points XDG_DATA_HOME at ~/.var/app/<id>/data, where the desktop
    menu would never find them.
    """
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "sandboxed"))
    assert paths.desktop_entries_dir() == Path.home() / ".local/share/applications"
    assert paths.user_icons_dir() == Path.home() / ".local/share/icons"


def test_applications_dir_is_under_home():
    assert paths.applications_dir() == Path.home() / "Applications"


def test_ensure_dir_is_idempotent(tmp_path):
    target = tmp_path / "a" / "b"
    assert paths.ensure_dir(target) == target
    assert paths.ensure_dir(target).is_dir()
