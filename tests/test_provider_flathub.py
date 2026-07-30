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


def test_install_runs_the_expected_command(app, bridge, state):
    provider = FlathubProvider(app, bridge, state)
    lines: list[str] = []
    provider.install(lines.append)

    (call,) = bridge.calls
    assert call.argv == [
        "flatpak", "install", "-y", "--noninteractive", "flathub", "com.obsproject.Studio",
    ]
    assert call.check is True


def test_install_streams_output(app, bridge, state):
    bridge.set_result(
        ["flatpak", "install", "-y", "--noninteractive", "flathub", "com.obsproject.Studio"],
        output="Installing...\nDone.",
    )
    provider = FlathubProvider(app, bridge, state)
    lines: list[str] = []
    provider.install(lines.append)
    assert lines == ["Installing...", "Done."]


def test_install_failure_raises_install_error_with_result(app, bridge, state):
    bridge.set_result(
        ["flatpak", "install", "-y", "--noninteractive", "flathub", "com.obsproject.Studio"],
        returncode=1,
        output="error: not found",
    )
    provider = FlathubProvider(app, bridge, state)
    with pytest.raises(InstallError) as excinfo:
        provider.install(lambda _: None)
    assert excinfo.value.result.returncode == 1
    assert "not found" in excinfo.value.result.output


def test_uninstall_runs_the_expected_command(app, bridge, state):
    provider = FlathubProvider(app, bridge, state)
    provider.uninstall(lambda _: None)
    (call,) = bridge.calls
    assert call.argv == ["flatpak", "uninstall", "-y", "com.obsproject.Studio"]


def test_uninstall_failure_raises_install_error(app, bridge, state):
    bridge.set_result(
        ["flatpak", "uninstall", "-y", "com.obsproject.Studio"], returncode=1, output="busy"
    )
    provider = FlathubProvider(app, bridge, state)
    with pytest.raises(InstallError):
        provider.uninstall(lambda _: None)


def test_supports_uninstall(app, bridge, state):
    assert FlathubProvider(app, bridge, state).supports_uninstall is True


def test_describe_source_and_preview(app, bridge, state):
    provider = FlathubProvider(app, bridge, state)
    assert "com.obsproject.Studio" in provider.describe_source()
    assert provider.command_preview() == (
        "flatpak install -y --noninteractive flathub com.obsproject.Studio"
    )
