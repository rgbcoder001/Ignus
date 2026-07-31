"""Desktop shortcut creation and removal."""

from __future__ import annotations

import stat
import sys

import pytest

from fake_bridge import FakeBridge
from ignis.core.desktop import build_entry
from ignis.core.shortcuts import (
    create_shortcut,
    desktop_dir,
    has_shortcut,
    remove_shortcut,
    shortcut_path,
)


@pytest.fixture
def bridge() -> FakeBridge:
    bridge = FakeBridge()
    bridge.spawn = lambda argv: bridge.calls.append(  # type: ignore[method-assign]
        type("Spawn", (), {"argv": list(argv), "on_line": None, "timeout": None, "check": False})()
    )
    return bridge


def entry_for(app_id: str = "obs") -> str:
    return build_entry(
        name="OBS Studio",
        comment="Record and stream",
        exec_argv=["flatpak", "run", "com.obsproject.Studio"],
        icon="com.obsproject.Studio",
        categories="AudioVideo;",
        app_id=app_id,
    )


def test_desktop_dir_uses_the_host_answer(bridge, tmp_path):
    """The folder is localised, so it must be asked for, not assumed."""
    localised = tmp_path / "Escritorio"
    bridge.set_result(["xdg-user-dir", "DESKTOP"], output=str(localised))
    assert desktop_dir(bridge) == localised


def test_desktop_dir_falls_back_when_the_command_fails(bridge):
    bridge.set_result(["xdg-user-dir", "DESKTOP"], returncode=127)
    assert desktop_dir(bridge).name == "Desktop"


def test_creates_a_shortcut(tmp_path, bridge):
    path = create_shortcut(tmp_path, "obs", entry_for(), bridge)
    assert path == shortcut_path(tmp_path, "obs")
    assert "flatpak" in path.read_text(encoding="utf-8")
    assert has_shortcut(tmp_path, "obs")


def test_creates_the_desktop_folder_if_missing(tmp_path, bridge):
    target = tmp_path / "Desktop"
    create_shortcut(target, "obs", entry_for(), bridge)
    assert has_shortcut(target, "obs")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_shortcut_is_executable(tmp_path, bridge):
    """KDE will not run a launcher without the executable bit."""
    path = create_shortcut(tmp_path, "obs", entry_for(), bridge)
    assert path.stat().st_mode & stat.S_IXUSR


def test_marks_the_shortcut_trusted(tmp_path, bridge):
    """GNOME hides launchers it does not consider trusted."""
    create_shortcut(tmp_path, "obs", entry_for(), bridge)
    assert any(
        call.argv[:2] == ["gio", "set"] and "metadata::trusted" in call.argv
        for call in bridge.calls
    )


def test_creating_twice_overwrites_cleanly(tmp_path, bridge):
    create_shortcut(tmp_path, "obs", entry_for(), bridge)
    create_shortcut(tmp_path, "obs", entry_for(), bridge)
    desktop_files = list(tmp_path.glob("*.desktop"))
    assert len(desktop_files) == 1
    assert not list(tmp_path.glob("*.tmp"))


def test_removes_our_own_shortcut(tmp_path, bridge):
    create_shortcut(tmp_path, "obs", entry_for(), bridge)
    remove_shortcut(tmp_path, "obs")
    assert not has_shortcut(tmp_path, "obs")


def test_removing_a_missing_shortcut_is_harmless(tmp_path):
    remove_shortcut(tmp_path, "obs")


def test_refuses_to_delete_a_file_ignis_did_not_write(tmp_path):
    """A same-named file from elsewhere is not ours to delete (rule 6)."""
    victim = shortcut_path(tmp_path, "obs")
    victim.write_text("[Desktop Entry]\nName=Someone's own launcher\n", encoding="utf-8")

    remove_shortcut(tmp_path, "obs")

    assert victim.exists()


def test_refuses_to_delete_a_shortcut_for_a_different_app(tmp_path, bridge):
    path = create_shortcut(tmp_path, "obs", entry_for("something-else"), bridge)
    remove_shortcut(tmp_path, "obs")
    assert path.exists()
