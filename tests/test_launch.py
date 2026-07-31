"""Launching installed apps and generating their shortcuts."""

from __future__ import annotations

import pytest

from fake_bridge import FakeBridge
from ignis.core import paths
from ignis.core.catalog import (
    App,
    Category,
    FlathubSource,
    GithubSource,
    InstallKind,
    ScriptSource,
    UjustSource,
)
from ignis.core.desktop import parse_exec
from ignis.core.state import State
from ignis.providers.base import NotSupportedError
from ignis.providers.flathub import FlathubProvider
from ignis.providers.github_release import GithubReleaseProvider
from ignis.providers.script import ScriptProvider
from ignis.providers.ujust import UjustProvider


@pytest.fixture
def state(tmp_path) -> State:
    return State.load(tmp_path / "state.json")


@pytest.fixture
def bridge() -> FakeBridge:
    bridge = FakeBridge()
    bridge.spawned: list[list[str]] = []

    def spawn(argv):
        bridge.spawned.append(list(argv))

    bridge.spawn = spawn  # type: ignore[method-assign]
    return bridge


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(
        paths, "desktop_entries_dir", lambda: tmp_path / ".local/share/applications"
    )
    return tmp_path


def flathub_app() -> App:
    return App(
        id="obs",
        name="OBS Studio",
        summary="Record and stream",
        category=Category.STREAMING,
        source=FlathubSource(ref="com.obsproject.Studio"),
    )


def github_app() -> App:
    return App(
        id="githublauncher",
        name="GitHub Launcher",
        summary="Install apps from GitHub",
        category=Category.EMULATION,
        source=GithubSource(
            repo="a/b", asset_pattern=r"\.zip$", install_kind=InstallKind.ZIP
        ),
    )


# -- Flathub -----------------------------------------------------------


def test_flathub_launches_with_flatpak_run(bridge, state):
    FlathubProvider(flathub_app(), bridge, state).launch()
    assert bridge.spawned == [["flatpak", "run", "com.obsproject.Studio"]]


def test_flathub_launch_does_not_block(bridge, state):
    """It must spawn, not run: run() would wait until the app is closed."""
    FlathubProvider(flathub_app(), bridge, state).launch()
    assert bridge.calls == []


def test_flathub_shortcut_runs_the_flatpak(bridge, state):
    entry = FlathubProvider(flathub_app(), bridge, state).shortcut_entry()
    assert parse_exec(entry) == ["flatpak", "run", "com.obsproject.Studio"]
    assert "Icon=com.obsproject.Studio" in entry
    assert "X-Ignis-App=obs" in entry


# -- GitHub releases ---------------------------------------------------


def test_github_launch_reuses_the_installed_launcher(bridge, state, home):
    provider = GithubReleaseProvider(github_app(), bridge, state)
    entry = provider.desktop_entry_path
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(
        '[Desktop Entry]\nExec="/home/me/Applications/githublauncher/GithubLauncher"\n',
        encoding="utf-8",
    )

    provider.launch()

    assert bridge.spawned == [["/home/me/Applications/githublauncher/GithubLauncher"]]


def test_github_launch_without_a_launcher_is_not_supported(bridge, state, home):
    provider = GithubReleaseProvider(github_app(), bridge, state)
    assert provider.launch_command() is None
    with pytest.raises(NotSupportedError):
        provider.launch()


def test_github_shortcut_copies_the_installed_launcher(bridge, state, home):
    provider = GithubReleaseProvider(github_app(), bridge, state)
    entry = provider.desktop_entry_path
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("[Desktop Entry]\nName=GitHub Launcher\n", encoding="utf-8")

    assert provider.shortcut_entry() == "[Desktop Entry]\nName=GitHub Launcher\n"


def test_github_shortcut_without_a_launcher_is_none(bridge, state, home):
    assert GithubReleaseProvider(github_app(), bridge, state).shortcut_entry() is None


# -- providers with nothing to launch ----------------------------------


@pytest.mark.parametrize(
    ("provider_class", "source"),
    [
        (UjustProvider, UjustSource(recipe="setup-sunshine", args=("enable",))),
        (ScriptProvider, ScriptSource(file="fix.sh")),
    ],
)
def test_providers_without_an_app_to_open(provider_class, source, bridge, state):
    """A recipe or a config script has nothing to launch, and must say so
    rather than pretending it worked."""
    app = App(
        id="x", name="X", summary="s", category=Category.SYSTEM, source=source
    )
    provider = provider_class(app, bridge, state)
    assert provider.launch_command() is None
    assert provider.shortcut_entry() is None
    with pytest.raises(NotSupportedError):
        provider.launch()
