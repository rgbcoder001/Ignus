"""FlathubProvider: status/install/uninstall via `flatpak`."""

from __future__ import annotations

import pytest

from fake_bridge import FakeBridge
from ignis.core.catalog import App, Category, FlathubSource
from ignis.core.state import State
from ignis.providers.base import InstallError, InstallStatus
from ignis.providers.flathub import FlathubProvider


@pytest.fixture
def app() -> App:
    return App(
        id="obs",
        name="OBS Studio",
        summary="Record and stream",
        category=Category.STREAMING,
        source=FlathubSource(ref="com.obsproject.Studio"),
    )


@pytest.fixture
def state(tmp_path) -> State:
    return State.load(tmp_path / "state.json")


@pytest.fixture
def bridge() -> FakeBridge:
    return FakeBridge()


def test_status_installed(app, bridge, state):
    bridge.set_result(["flatpak", "info", "com.obsproject.Studio"], returncode=0)
    provider = FlathubProvider(app, bridge, state)
    assert provider.status() is InstallStatus.INSTALLED


def test_status_not_installed(app, bridge, state):
    bridge.set_result(["flatpak", "info", "com.obsproject.Studio"], returncode=1)
    provider = FlathubProvider(app, bridge, state)
    assert provider.status() is InstallStatus.NOT_INSTALLED


USER_REMOTES = ["flatpak", "remotes", "--user", "--columns=name"]
SYSTEM_REMOTES = ["flatpak", "remotes", "--system", "--columns=name"]
INSTALL_USER = [
    "flatpak", "install", "-y", "--noninteractive",
    "--user", "flathub", "com.obsproject.Studio",
]


def with_user_flathub(bridge: FakeBridge) -> FakeBridge:
    """Bazzite's layout: the flathub remote exists in both installations."""
    bridge.set_result(USER_REMOTES, output="Name\nflathub\nfedora")
    bridge.set_result(SYSTEM_REMOTES, output="Name\nflathub")
    return bridge


def test_install_states_the_scope_explicitly(app, bridge, state):
    """Bazzite has flathub in both installations, and an unqualified install
    fails with "Remote 'flathub' found in multiple installations"."""
    with_user_flathub(bridge)
    FlathubProvider(app, bridge, state).install(lambda _: None)

    install_calls = [c for c in bridge.calls if c.argv[1] == "install"]
    assert [c.argv for c in install_calls] == [INSTALL_USER]


def test_install_falls_back_to_system_when_only_it_has_flathub(app, bridge, state):
    bridge.set_result(USER_REMOTES, output="Name\nfedora")
    bridge.set_result(SYSTEM_REMOTES, output="Name\nflathub")
    FlathubProvider(app, bridge, state).install(lambda _: None)

    install_call = next(c for c in bridge.calls if c.argv[1] == "install")
    assert "--system" in install_call.argv
    assert "--user" not in install_call.argv


def test_install_without_flathub_anywhere_explains_how_to_add_it(app, bridge, state):
    bridge.set_result(USER_REMOTES, output="Name\nfedora")
    bridge.set_result(SYSTEM_REMOTES, output="Name\nfedora")
    with pytest.raises(InstallError) as excinfo:
        FlathubProvider(app, bridge, state).install(lambda _: None)
    assert "remote-add" in str(excinfo.value)


def test_remote_matching_is_exact_not_substring(app, bridge, state):
    """A remote merely containing 'flathub' must not be mistaken for it."""
    bridge.set_result(USER_REMOTES, output="Name\nflathub-beta")
    bridge.set_result(SYSTEM_REMOTES, output="Name\nflathub")
    FlathubProvider(app, bridge, state).install(lambda _: None)
    install_call = next(c for c in bridge.calls if c.argv[1] == "install")
    assert "--system" in install_call.argv


def test_install_streams_output(app, bridge, state):
    with_user_flathub(bridge)
    bridge.set_result(INSTALL_USER, output="Installing...\nDone.")
    lines: list[str] = []
    FlathubProvider(app, bridge, state).install(lines.append)
    assert lines == ["Installing...", "Done."]


def test_install_failure_raises_install_error_with_result(app, bridge, state):
    with_user_flathub(bridge)
    bridge.set_result(INSTALL_USER, returncode=1, output="error: not found")
    with pytest.raises(InstallError) as excinfo:
        FlathubProvider(app, bridge, state).install(lambda _: None)
    assert excinfo.value.result.returncode == 1
    assert "not found" in excinfo.value.result.output


def test_uninstall_targets_the_installation_the_app_is_in(app, bridge, state):
    """A system-installed app must not be uninstalled with --user."""
    bridge.set_result(["flatpak", "info", "--user", "com.obsproject.Studio"], returncode=1)
    bridge.set_result(["flatpak", "info", "--system", "com.obsproject.Studio"], returncode=0)

    FlathubProvider(app, bridge, state).uninstall(lambda _: None)

    call = next(c for c in bridge.calls if c.argv[1] == "uninstall")
    assert call.argv == [
        "flatpak", "uninstall", "-y", "--noninteractive",
        "--system", "com.obsproject.Studio",
    ]


def test_uninstall_prefers_the_user_installation(app, bridge, state):
    bridge.set_result(["flatpak", "info", "--user", "com.obsproject.Studio"], returncode=0)
    FlathubProvider(app, bridge, state).uninstall(lambda _: None)
    call = next(c for c in bridge.calls if c.argv[1] == "uninstall")
    assert "--user" in call.argv


def test_uninstall_of_a_missing_app_is_a_clear_error(app, bridge, state):
    bridge.set_result(["flatpak", "info", "--user", "com.obsproject.Studio"], returncode=1)
    bridge.set_result(["flatpak", "info", "--system", "com.obsproject.Studio"], returncode=1)
    with pytest.raises(InstallError) as excinfo:
        FlathubProvider(app, bridge, state).uninstall(lambda _: None)
    assert "doesn't appear to be installed" in str(excinfo.value)


def test_supports_uninstall(app, bridge, state):
    assert FlathubProvider(app, bridge, state).supports_uninstall is True


def test_describe_source_and_preview(app, bridge, state):
    provider = FlathubProvider(app, bridge, state)
    assert "com.obsproject.Studio" in provider.describe_source()
    assert provider.command_preview() == (
        "flatpak install -y --noninteractive --user flathub com.obsproject.Studio"
    )


def test_status_is_not_scoped(app, bridge, state):
    """An app should read as installed whether the user installed it or it
    shipped with the system."""
    bridge.set_result(["flatpak", "info", "com.obsproject.Studio"], returncode=0)
    assert FlathubProvider(app, bridge, state).status() is InstallStatus.INSTALLED
