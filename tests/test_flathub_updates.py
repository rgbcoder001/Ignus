"""Flathub update detection and the update action."""

from __future__ import annotations

import pytest

from fake_bridge import FakeBridge
from ignis.core.catalog import App, Category, FlathubSource
from ignis.core.state import State
from ignis.providers.base import InstallError
from ignis.providers.flathub import (
    FlathubProvider,
    parse_application_column,
    updatable_refs,
)

USER_UPDATES = [
    "flatpak", "remote-ls", "--updates", "--user", "--columns=application",
]
SYSTEM_UPDATES = [
    "flatpak", "remote-ls", "--updates", "--system", "--columns=application",
]


@pytest.fixture
def state(tmp_path) -> State:
    return State.load(tmp_path / "state.json")


@pytest.fixture
def bridge() -> FakeBridge:
    return FakeBridge()


@pytest.fixture
def app() -> App:
    return App(
        id="obs",
        name="OBS Studio",
        summary="Record and stream",
        category=Category.STREAMING,
        source=FlathubSource(ref="com.obsproject.Studio"),
    )


def test_parses_the_application_column():
    output = "Application\ncom.obsproject.Studio\nio.mpv.Mpv\n"
    assert parse_application_column(output) == {"com.obsproject.Studio", "io.mpv.Mpv"}


def test_parsing_tolerates_a_missing_header():
    """flatpak only prints a header when attached to a terminal."""
    assert parse_application_column("io.mpv.Mpv\n") == {"io.mpv.Mpv"}


def test_parsing_ignores_blank_lines():
    assert parse_application_column("\n\nio.mpv.Mpv\n\n") == {"io.mpv.Mpv"}


def test_parsing_empty_output_yields_nothing():
    assert parse_application_column("") == set()


def test_collects_updates_from_both_installations(bridge):
    bridge.set_result(USER_UPDATES, output="Application\nio.mpv.Mpv")
    bridge.set_result(SYSTEM_UPDATES, output="Application\ncom.obsproject.Studio")
    assert updatable_refs(bridge) == frozenset(
        {"io.mpv.Mpv", "com.obsproject.Studio"}
    )


def test_a_failing_installation_query_does_not_lose_the_other(bridge):
    bridge.set_result(USER_UPDATES, output="Application\nio.mpv.Mpv")
    bridge.set_result(SYSTEM_UPDATES, returncode=1, output="error: no remote")
    assert updatable_refs(bridge) == frozenset({"io.mpv.Mpv"})


def test_no_updates_is_an_empty_set_not_an_error(bridge):
    bridge.set_result(USER_UPDATES, output="Application")
    bridge.set_result(SYSTEM_UPDATES, output="Application")
    assert updatable_refs(bridge) == frozenset()


def test_update_targets_the_installation_the_app_is_in(app, bridge, state):
    bridge.set_result(["flatpak", "info", "--user", "com.obsproject.Studio"], returncode=1)
    bridge.set_result(["flatpak", "info", "--system", "com.obsproject.Studio"], returncode=0)

    FlathubProvider(app, bridge, state).update(lambda _: None)

    call = next(c for c in bridge.calls if c.argv[1] == "update")
    assert call.argv == [
        "flatpak", "update", "-y", "--noninteractive",
        "--system", "com.obsproject.Studio",
    ]


def test_updating_something_not_installed_is_a_clear_error(app, bridge, state):
    bridge.set_result(["flatpak", "info", "--user", "com.obsproject.Studio"], returncode=1)
    bridge.set_result(["flatpak", "info", "--system", "com.obsproject.Studio"], returncode=1)
    with pytest.raises(InstallError) as excinfo:
        FlathubProvider(app, bridge, state).update(lambda _: None)
    assert "doesn't appear to be installed" in str(excinfo.value)


def test_update_failure_carries_the_command_result(app, bridge, state):
    bridge.set_result(["flatpak", "info", "--user", "com.obsproject.Studio"], returncode=0)
    bridge.set_result(
        ["flatpak", "update", "-y", "--noninteractive", "--user", "com.obsproject.Studio"],
        returncode=1,
        output="error: no network",
    )
    with pytest.raises(InstallError) as excinfo:
        FlathubProvider(app, bridge, state).update(lambda _: None)
    assert excinfo.value.result.returncode == 1
