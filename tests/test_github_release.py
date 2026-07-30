"""GithubReleaseProvider: status, extraction, executable choice, safe removal."""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

import pytest

from fake_bridge import FakeBridge
from ignis.core import paths
from ignis.core.catalog import App, Category, GithubSource, InstallKind
from ignis.core.state import InstalledApp, State
from ignis.providers.base import InstallError, InstallStatus
from ignis.providers.github_api import GithubClient
from ignis.providers.github_release import (
    GithubReleaseProvider,
    _desktop_entry,
    _extract_tar,
    _extract_zip,
    _find_executable,
    _quote_exec,
    _remove_files,
    is_deletable,
)

ELF = b"\x7fELF" + b"\x00" * 60

PAYLOAD = {
    "tag_name": "v1.73",
    "assets": [
        {
            "name": "app-linux-x64.zip",
            "browser_download_url": "https://example.invalid/a.zip",
            "size": 10,
        }
    ],
}


@pytest.fixture
def state(tmp_path) -> State:
    return State.load(tmp_path / "state.json")


@pytest.fixture
def app() -> App:
    return App(
        id="githublauncher",
        name="GitHub Launcher",
        summary="Install apps from GitHub",
        category=Category.EMULATION,
        source=GithubSource(
            repo="SirDiabo/GithubLauncher",
            asset_pattern=r"linux-x64\.zip$",
            install_kind=InstallKind.ZIP,
        ),
    )


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Redirect every install location into a temp tree."""
    root = tmp_path / "home"
    monkeypatch.setattr(paths, "applications_dir", lambda: root / "Applications")
    monkeypatch.setattr(
        paths, "desktop_entries_dir", lambda: root / ".local/share/applications"
    )
    monkeypatch.setattr(paths, "user_icons_dir", lambda: root / ".local/share/icons")
    return root


def provider(app, state, bridge=None) -> GithubReleaseProvider:
    return GithubReleaseProvider(app, bridge or FakeBridge(), state, GithubClient(state, None))


# -- status ------------------------------------------------------------


def test_status_not_installed(app, state):
    assert provider(app, state).status() is InstallStatus.NOT_INSTALLED


def test_status_installed_when_tags_match(app, state):
    state.set_installed(app.id, InstalledApp(tag="v1.73"))
    state.set_cache(app.source.repo, "etag", PAYLOAD)
    assert provider(app, state).status() is InstallStatus.INSTALLED


def test_status_update_available_when_cached_tag_is_newer(app, state):
    state.set_installed(app.id, InstalledApp(tag="v1.72"))
    state.set_cache(app.source.repo, "etag", PAYLOAD)
    assert provider(app, state).status() is InstallStatus.UPDATE_AVAILABLE


def test_status_installed_without_a_cache_does_not_claim_an_update(app, state):
    state.set_installed(app.id, InstalledApp(tag="v1.72"))
    assert provider(app, state).status() is InstallStatus.INSTALLED


# -- extraction --------------------------------------------------------


def make_zip(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as bundle:
        for name, data in entries.items():
            bundle.writestr(name, data)
    return path


def make_tar(path: Path, entries: dict[str, bytes]) -> Path:
    with tarfile.open(path, "w:gz") as tar:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def test_extract_zip_returns_the_files(tmp_path):
    archive = make_zip(tmp_path / "a.zip", {"bin/app": ELF, "readme.txt": b"hi"})
    files = _extract_zip(archive, tmp_path / "out")
    assert {f.name for f in files} == {"app", "readme.txt"}


def test_extract_tar_returns_the_files(tmp_path):
    archive = make_tar(tmp_path / "a.tar.gz", {"app": ELF})
    files = _extract_tar(archive, tmp_path / "out")
    assert [f.name for f in files] == ["app"]


def test_zip_traversal_cannot_escape_the_target(tmp_path):
    """zip slip: ../ members must not land outside the install directory."""
    archive = make_zip(tmp_path / "evil.zip", {"../escaped.txt": b"pwned"})
    target = tmp_path / "out"
    _extract_zip(archive, target)
    assert not (tmp_path / "escaped.txt").exists()


def test_corrupt_archive_is_an_install_error(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(InstallError):
        _extract_zip(bad, tmp_path / "out")


# -- executable selection ----------------------------------------------


def test_prefers_an_elf_binary_over_a_bigger_data_file(tmp_path):
    small = tmp_path / "app"
    small.write_bytes(ELF)
    big = tmp_path / "assets.dat"
    big.write_bytes(b"x" * 10_000)
    assert _find_executable([small, big], "app") == small


def test_prefers_the_binary_matching_the_app_name(tmp_path):
    """The real GithubLauncher zip ships three ELF .so files beside the app."""
    launcher = tmp_path / "GithubLauncher"
    launcher.write_bytes(ELF)
    sdl = tmp_path / "libSDL2.so"
    sdl.write_bytes(ELF + b"x" * 50_000)
    assert _find_executable([launcher, sdl], "GitHub Launcher") == launcher


def test_falls_back_to_the_largest_file_when_nothing_looks_executable(tmp_path):
    small = tmp_path / "a.txt"
    small.write_bytes(b"x")
    large = tmp_path / "b.txt"
    large.write_bytes(b"x" * 100)
    assert _find_executable([small, large], "nothing") == large


def test_no_files_is_an_install_error():
    with pytest.raises(InstallError):
        _find_executable([], "app")


# -- desktop entry -----------------------------------------------------


def test_desktop_entry_contents(app, tmp_path):
    entry = _desktop_entry(app, tmp_path / "Apps" / "GithubLauncher")
    assert "[Desktop Entry]" in entry
    assert "Name=GitHub Launcher" in entry
    assert "Comment=Install apps from GitHub" in entry
    assert "Categories=Game;Emulator;" in entry
    assert "X-Ignis-App=githublauncher" in entry
    assert "Terminal=false" in entry
    exec_line = next(line for line in entry.splitlines() if line.startswith("Exec="))
    assert exec_line.startswith('Exec="') and exec_line.endswith('"')
    assert "GithubLauncher" in exec_line


def test_desktop_exec_quoting_escapes_special_characters():
    """Paths are quoted per the .desktop spec, whatever they contain."""
    assert _quote_exec(PurePosixPath("/home/me/Apps/My App/run")) == '"/home/me/Apps/My App/run"'
    assert _quote_exec(PurePosixPath('/tmp/od"d')) == '"/tmp/od\\"d"'


# -- destructive-operation guard ---------------------------------------


def test_files_inside_our_own_directories_are_deletable(home):
    assert is_deletable(paths.applications_dir() / "app" / "bin")
    assert is_deletable(paths.desktop_entries_dir() / "ignis-app.desktop")
    assert is_deletable(paths.user_icons_dir() / "app.png")


def test_paths_outside_our_directories_are_never_deletable(home, tmp_path):
    """state.json is user-writable; a corrupt record must not delete anything."""
    assert not is_deletable(Path("/etc/passwd"))
    assert not is_deletable(Path.home() / "Documents" / "taxes.pdf")
    assert not is_deletable(tmp_path / "elsewhere.txt")


def test_traversal_out_of_our_directories_is_rejected(home):
    assert not is_deletable(paths.applications_dir() / ".." / ".." / "secrets")


def test_remove_files_skips_unsafe_paths_and_says_so(home, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("keep me", encoding="utf-8")
    inside = paths.applications_dir() / "app" / "file"
    inside.parent.mkdir(parents=True)
    inside.write_text("delete me", encoding="utf-8")

    lines: list[str] = []
    _remove_files([outside, inside], lines.append)

    assert outside.exists(), "a file outside Ignis's folders must survive"
    assert not inside.exists()
    assert any("refusing to delete" in line for line in lines)


def test_remove_files_tolerates_already_missing_files(home):
    _remove_files([paths.applications_dir() / "gone"], lambda _l: None)


# -- uninstall ---------------------------------------------------------


def test_uninstall_without_a_record_is_a_clear_error(app, state, home):
    with pytest.raises(InstallError) as excinfo:
        provider(app, state).uninstall(lambda _l: None)
    assert "not recorded" in str(excinfo.value)


def test_uninstall_removes_recorded_files_and_clears_state(app, state, home):
    target = paths.applications_dir() / app.id
    target.mkdir(parents=True)
    binary = target / "GithubLauncher"
    binary.write_bytes(ELF)
    entry = paths.desktop_entries_dir() / f"ignis-{app.id}.desktop"
    entry.parent.mkdir(parents=True)
    entry.write_text("[Desktop Entry]", encoding="utf-8")

    state.set_installed(app.id, InstalledApp(tag="v1.73", files=(str(binary), str(entry))))
    bridge = FakeBridge()
    provider(app, state, bridge).uninstall(lambda _l: None)

    assert not binary.exists()
    assert not entry.exists()
    assert state.installed(app.id) is None
    assert not target.exists(), "the now-empty app directory should be pruned"
