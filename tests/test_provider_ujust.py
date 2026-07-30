"""UjustProvider: runs Bazzite's built-in recipes."""

from __future__ import annotations

import pytest

from fake_bridge import FakeBridge
from ignis.core.catalog import App, Category, UjustSource
from ignis.core.state import State
from ignis.providers.base import InstallError, InstallStatus, NotSupportedError
from ignis.providers.ujust import UjustProvider


@pytest.fixture
def state(tmp_path) -> State:
    return State.load(tmp_path / "state.json")


@pytest.fixture
def bridge() -> FakeBridge:
    return FakeBridge()


def make_app(check_cmd=None) -> App:
    return App(
        id="emudeck",
        name="EmuDeck",
        summary="Emulation setup",
        category=Category.EMULATION,
        source=UjustSource(recipe="install-emudeck", check_cmd=check_cmd),
    )


def test_status_unknown_without_check_cmd(bridge, state):
    provider = UjustProvider(make_app(), bridge, state)
    assert provider.status() is InstallStatus.UNKNOWN
    assert bridge.calls == []


def test_status_installed_with_check_cmd(bridge, state):
    bridge.set_result(["test", "-d", "/home/.emudeck"], returncode=0)
    provider = UjustProvider(make_app(check_cmd=("test", "-d", "/home/.emudeck")), bridge, state)
    assert provider.status() is InstallStatus.INSTALLED


def test_status_not_installed_with_check_cmd(bridge, state):
    bridge.set_result(["test", "-d", "/home/.emudeck"], returncode=1)
    provider = UjustProvider(make_app(check_cmd=("test", "-d", "/home/.emudeck")), bridge, state)
    assert provider.status() is InstallStatus.NOT_INSTALLED


def test_install_runs_the_recipe(bridge, state):
    provider = UjustProvider(make_app(), bridge, state)
    provider.install(lambda _: None)
    (call,) = bridge.calls
    assert call.argv == ["ujust", "install-emudeck"]


def test_install_failure_raises_install_error(bridge, state):
    bridge.set_result(["ujust", "install-emudeck"], returncode=1, output="boom")
    provider = UjustProvider(make_app(), bridge, state)
    with pytest.raises(InstallError) as excinfo:
        provider.install(lambda _: None)
    assert excinfo.value.result.returncode == 1


def test_uninstall_not_supported(bridge, state):
    provider = UjustProvider(make_app(), bridge, state)
    assert provider.supports_uninstall is False
    with pytest.raises(NotSupportedError):
        provider.uninstall(lambda _: None)


def test_describe_source_and_preview(bridge, state):
    provider = UjustProvider(make_app(), bridge, state)
    assert "install-emudeck" in provider.describe_source()
    assert provider.command_preview() == "ujust install-emudeck"
