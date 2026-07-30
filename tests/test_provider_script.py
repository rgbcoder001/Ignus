"""ScriptProvider: runs a bundled script by content, not by path.

Inside the Flatpak sandbox, the script's real path (/app/share/ignis/...) is
invisible to flatpak-spawn --host, so the provider must read the file here
and send its *content* to the host via `bash -c`. These tests exercise that
directly against FakeBridge.
"""

from __future__ import annotations

import pytest

from fake_bridge import FakeBridge
from ignis.core import paths
from ignis.core.catalog import App, Category, ScriptSource
from ignis.core.state import State
from ignis.providers.base import InstallError, InstallStatus, NotSupportedError
from ignis.providers.script import ScriptProvider


@pytest.fixture
def state(tmp_path) -> State:
    return State.load(tmp_path / "state.json")


@pytest.fixture
def bridge() -> FakeBridge:
    return FakeBridge()


@pytest.fixture
def scripts_dir(tmp_path, monkeypatch):
    directory = tmp_path / "scripts"
    directory.mkdir()
    monkeypatch.setattr(paths, "scripts_dir", lambda: directory)
    return directory


def make_app(check_cmd=None, post_install=None) -> App:
    return App(
        id="discord-fix",
        name="Discord Fix",
        summary="Fixes Discord screenshare",
        category=Category.SYSTEM,
        source=ScriptSource(file="discord-fix.sh", check_cmd=check_cmd),
        post_install=post_install,
    )


def test_install_sends_script_content_via_bash_c(scripts_dir, bridge, state):
    (scripts_dir / "discord-fix.sh").write_text("echo hello\n", encoding="utf-8")
    provider = ScriptProvider(make_app(), bridge, state)
    provider.install(lambda _: None)

    (call,) = bridge.calls
    assert call.argv == ["bash", "-c", "echo hello\n"]


def test_install_streams_output(scripts_dir, bridge, state):
    (scripts_dir / "discord-fix.sh").write_text("echo hi", encoding="utf-8")
    bridge.set_result(["bash", "-c", "echo hi"], output="hi")
    provider = ScriptProvider(make_app(), bridge, state)
    lines: list[str] = []
    provider.install(lines.append)
    assert lines == ["hi"]


def test_install_failure_raises_install_error(scripts_dir, bridge, state):
    (scripts_dir / "discord-fix.sh").write_text("exit 1", encoding="utf-8")
    bridge.set_result(["bash", "-c", "exit 1"], returncode=1, output="boom")
    provider = ScriptProvider(make_app(), bridge, state)
    with pytest.raises(InstallError) as excinfo:
        provider.install(lambda _: None)
    assert excinfo.value.result.returncode == 1


def test_missing_script_file_raises_install_error_not_crash(scripts_dir, bridge, state):
    """A catalog/scripts-dir mismatch must be a clean error, never a crash."""
    provider = ScriptProvider(make_app(), bridge, state)
    with pytest.raises(InstallError):
        provider.install(lambda _: None)
    assert bridge.calls == []  # never even reached the bridge


def test_status_unknown_without_check_cmd(scripts_dir, bridge, state):
    provider = ScriptProvider(make_app(), bridge, state)
    assert provider.status() is InstallStatus.UNKNOWN


def test_status_from_check_cmd(scripts_dir, bridge, state):
    bridge.set_result(["test", "-f", "/marker"], returncode=0)
    provider = ScriptProvider(make_app(check_cmd=("test", "-f", "/marker")), bridge, state)
    assert provider.status() is InstallStatus.INSTALLED


def test_uninstall_not_supported(scripts_dir, bridge, state):
    provider = ScriptProvider(make_app(), bridge, state)
    assert provider.supports_uninstall is False
    with pytest.raises(NotSupportedError):
        provider.uninstall(lambda _: None)


def test_run_install_runs_post_install_script(scripts_dir, bridge, state):
    (scripts_dir / "discord-fix.sh").write_text("echo main", encoding="utf-8")
    (scripts_dir / "post.sh").write_text("echo post", encoding="utf-8")
    provider = ScriptProvider(make_app(post_install="post.sh"), bridge, state)

    lines: list[str] = []
    provider.run_install(lines.append)

    assert [call.argv for call in bridge.calls] == [
        ["bash", "-c", "echo main"],
        ["bash", "-c", "echo post"],
    ]
    assert any("post-install" in line for line in lines)


def test_run_install_skips_post_install_when_unset(scripts_dir, bridge, state):
    (scripts_dir / "discord-fix.sh").write_text("echo main", encoding="utf-8")
    provider = ScriptProvider(make_app(), bridge, state)
    provider.run_install(lambda _: None)
    assert len(bridge.calls) == 1
