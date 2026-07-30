"""HostBridge execution, streaming, and failure handling.

These tests run real subprocesses using the current Python interpreter, so
they work on any OS.
"""

from __future__ import annotations

import sys

import pytest

from ignis.core.host import (
    EXIT_NOT_FOUND,
    EXIT_TIMEOUT,
    HOST_PREFIX,
    CommandError,
    CommandResult,
    HostBridge,
)


@pytest.fixture
def bridge() -> HostBridge:
    """A bridge that runs commands directly (no sandbox)."""
    return HostBridge(use_host_spawn=False)


def python(code: str) -> list[str]:
    """argv running a snippet with the current interpreter."""
    return [sys.executable, "-c", code]


def test_runs_a_command_and_captures_output(bridge):
    result = bridge.run(python("print('hello')"))
    assert result.ok
    assert result.returncode == 0
    assert "hello" in result.output


def test_merges_stderr_into_output(bridge):
    result = bridge.run(python("import sys; sys.stderr.write('oops\\n')"))
    assert "oops" in result.output


def test_streams_lines_to_callback(bridge):
    seen: list[str] = []
    bridge.run(python("print('one'); print('two')"), on_line=seen.append)
    assert seen == ["one", "two"]


def test_callback_exception_does_not_break_the_run(bridge):
    def boom(_line: str) -> None:
        raise RuntimeError("bad UI callback")

    result = bridge.run(python("print('still works')"), on_line=boom)
    assert result.ok
    assert "still works" in result.output


def test_nonzero_exit_raises_with_the_result(bridge):
    with pytest.raises(CommandError) as excinfo:
        bridge.run(python("import sys; print('why'); sys.exit(3)"))
    assert excinfo.value.result.returncode == 3
    assert "why" in excinfo.value.result.output


def test_check_false_returns_instead_of_raising(bridge):
    result = bridge.run(python("import sys; sys.exit(3)"), check=False)
    assert not result.ok
    assert result.returncode == 3


def test_missing_executable_is_reported_not_crashed(bridge):
    result = bridge.run(["ignis-definitely-not-a-real-command"], check=False)
    assert result.returncode == EXIT_NOT_FOUND
    assert "not found" in result.output.lower()


def test_timeout_terminates_and_reports(bridge):
    result = bridge.run(
        python("import time; time.sleep(30)"), timeout=1, check=False
    )
    assert result.returncode == EXIT_TIMEOUT
    assert "timed out" in result.output


def test_check_helper_never_raises(bridge):
    assert bridge.check(python("pass"))
    assert not bridge.check(["ignis-definitely-not-a-real-command"])


def test_host_spawn_prefix_is_applied_when_sandboxed():
    sandboxed = HostBridge(use_host_spawn=True)
    assert sandboxed.uses_host_spawn
    assert sandboxed.resolve_argv(["flatpak", "--version"]) == [
        *HOST_PREFIX,
        "flatpak",
        "--version",
    ]


def test_no_prefix_outside_the_sandbox(bridge):
    assert bridge.resolve_argv(["flatpak", "--version"]) == ["flatpak", "--version"]


def test_result_reports_the_user_facing_command(bridge):
    """argv shown to the user excludes the flatpak-spawn plumbing."""
    result = HostBridge(use_host_spawn=True).run(
        ["ignis-definitely-not-a-real-command"], check=False
    )
    assert result.argv == ["ignis-definitely-not-a-real-command"]


def test_command_result_helpers():
    result = CommandResult(argv=["ls", "-l", "a b"], returncode=1, output="x\ny\nz")
    assert "'a b'" in result.command
    assert result.tail(2) == "y\nz"
    assert not result.ok
