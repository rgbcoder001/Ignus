"""Shortening a command for the failure line.

A script entry's command is the whole script sent to the host. Rendered
verbatim into a wrapping label it grew to hundreds of lines, squeezing the
output view to nothing and pushing the buttons out of a fixed-height dialog —
which is how a failed NAS install ended up unreadable and unclosable.

The label itself is capped in the widget; this covers the text going into it.
Imported directly so no GTK is needed to run it.
"""

from __future__ import annotations

from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src/ignis/views/progress.py"


def load_short_command():
    """Pull short_command out of progress.py without importing gi."""
    text = SOURCE.read_text(encoding="utf-8")
    start = text.index("COMMAND_SUMMARY_CHARS")
    end = text.index("class ProgressDialog")
    namespace: dict = {}
    exec(compile(text[start:end], str(SOURCE), "exec"), namespace)  # noqa: S102
    return namespace["short_command"], namespace["COMMAND_SUMMARY_CHARS"]


short_command, LIMIT = load_short_command()


def test_a_short_command_is_left_alone():
    command = "flatpak install -y --user flathub org.videolan.VLC"
    assert short_command(command) == command


def test_a_whole_script_becomes_one_line():
    script = "bash -c '#!/usr/bin/env bash\n" + "echo hello\n" * 200 + "'"
    result = short_command(script)
    assert "\n" not in result
    assert len(result) <= LIMIT


def test_a_long_single_line_is_truncated_with_an_ellipsis():
    result = short_command("x" * 500)
    assert len(result) <= LIMIT
    assert result.endswith("…")


def test_a_multi_line_command_is_marked_as_having_more():
    assert short_command("first line\nsecond line").endswith("…")


def test_empty_input_does_not_raise():
    assert short_command("") == ""
    assert short_command("   ") == ""
