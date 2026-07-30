"""UjustProvider: runs Bazzite's built-in recipes non-interactively."""

from __future__ import annotations

import pytest

from fake_bridge import FakeBridge
from ignis.core.catalog import App, Category, UjustSource
from ignis.core.state import State
from ignis.providers.base import InstallError, InstallStatus, NotSupportedError
from ignis.providers.ujust import UjustProvider, needs_terminal

# Real output from `ujust setup-sunshine` with no action, captured on Bazzite.
# Note it exited 0 despite doing nothing.
TTY_OUTPUT = (
    "Service is Not Installed\n"
    "unable to pick selection: could not open a new TTY: "
    "open /dev/tty: no such device or address"
)


@pytest.fixture
def state(tmp_path) -> State:
    return State.load(tmp_path / "state.json")


@pytest.fixture
def bridge() -> FakeBridge:
    return FakeBridge()


def make_app(args=(), uninstall_args=None, check_cmd=None) -> App:
    return App(
        id="emudeck",
        name="EmuDeck",
        summary="Emulation setup",
        category=Category.EMULATION,
        source=UjustSource(
            recipe="install-emudeck",
            args=args,
            uninstall_args=uninstall_args,
            check_cmd=check_cmd,
        ),
    )


def test_install_passes_the_configured_action(bridge, state):
    """Without an action the recipe opens a menu Ignis cannot answer."""
    UjustProvider(make_app(args=("install",)), bridge, state).install(lambda _: None)
    (call,) = bridge.calls
    assert call.argv == ["ujust", "install-emudeck", "install"]


def test_interactive_menu_is_a_failure_even_when_the_exit_code_is_zero(bridge, state):
    """setup-sunshine printed the TTY error and still exited 0 — reporting
    that as a successful install is the worst possible outcome."""
    bridge.set_result(["ujust", "install-emudeck"], returncode=0, output=TTY_OUTPUT)
    provider = UjustProvider(make_app(), bridge, state)

    with pytest.raises(InstallError) as excinfo:
        provider.install(lambda _: None)
    assert "interactive menu" in str(excinfo.value)
    assert excinfo.value.result is not None


def test_interactive_menu_is_detected_on_a_failing_exit_too(bridge, state):
    bridge.set_result(
        ["ujust", "install-emudeck"],
        returncode=1,
        output="unable to pick selection: could not open a new TTY",
    )
    with pytest.raises(InstallError) as excinfo:
        UjustProvider(make_app(), bridge, state).install(lambda _: None)
    assert "interactive menu" in str(excinfo.value)


@pytest.mark.parametrize(
    "output",
    [
        "unable to pick selection: could not open a new TTY",
        "open /dev/tty: no such device or address",
        "COULD NOT OPEN A NEW TTY",
    ],
)
def test_needs_terminal_recognises_the_markers(output):
    assert needs_terminal(output)


def test_needs_terminal_ignores_ordinary_output():
    assert not needs_terminal("Installing EmuDeck...\nDone.")


def test_ordinary_failure_still_reports_the_exit_code(bridge, state):
    bridge.set_result(
        ["ujust", "install-emudeck", "install"], returncode=1, output="disk full"
    )
    with pytest.raises(InstallError) as excinfo:
        UjustProvider(make_app(args=("install",)), bridge, state).install(lambda _: None)
    assert excinfo.value.result.returncode == 1


def test_install_streams_output(bridge, state):
    bridge.set_result(["ujust", "install-emudeck", "install"], output="one\ntwo")
    lines: list[str] = []
    UjustProvider(make_app(args=("install",)), bridge, state).install(lines.append)
    assert lines == ["one", "two"]


def test_uninstall_uses_the_configured_action(bridge, state):
    app = make_app(args=("install",), uninstall_args=("uninstall",))
    provider = UjustProvider(app, bridge, state)
    assert provider.supports_uninstall is True

    provider.uninstall(lambda _: None)
    (call,) = bridge.calls
    assert call.argv == ["ujust", "install-emudeck", "uninstall"]


def test_uninstall_unsupported_without_a_configured_action(bridge, state):
    provider = UjustProvider(make_app(args=("install",)), bridge, state)
    assert provider.supports_uninstall is False
    with pytest.raises(NotSupportedError):
        provider.uninstall(lambda _: None)


def test_status_unknown_without_check_cmd(bridge, state):
    assert UjustProvider(make_app(), bridge, state).status() is InstallStatus.UNKNOWN
    assert bridge.calls == []


def test_status_installed_with_check_cmd(bridge, state):
    bridge.set_result(["test", "-d", "/marker"], returncode=0)
    app = make_app(check_cmd=("test", "-d", "/marker"))
    assert UjustProvider(app, bridge, state).status() is InstallStatus.INSTALLED


def test_status_not_installed_with_check_cmd(bridge, state):
    bridge.set_result(["test", "-d", "/marker"], returncode=1)
    app = make_app(check_cmd=("test", "-d", "/marker"))
    assert UjustProvider(app, bridge, state).status() is InstallStatus.NOT_INSTALLED


def test_describe_source_and_preview(bridge, state):
    provider = UjustProvider(make_app(args=("install",)), bridge, state)
    assert "install-emudeck" in provider.describe_source()
    assert provider.command_preview() == "ujust install-emudeck install"
