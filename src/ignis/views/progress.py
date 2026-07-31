"""Live command-output dialog shown while an install/uninstall runs.

Not closable while running (SPEC.md §5): the user must see the outcome. On
failure it shows the exact failing command and offers the log, per
CLAUDE.md's "no silent failures" rule.
"""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk, Pango  # noqa: E402

from ignis.core.host import CommandResult
from ignis.views.common import open_log_folder

log = logging.getLogger(__name__)

#: Longest command text worth putting in the failure line.
COMMAND_SUMMARY_CHARS = 120


def short_command(command: str) -> str:
    """A one-line version of a command, fit to show in a label.

    Bundled scripts are sent to the host as their whole contents, so a
    script entry's command is the entire file. Showing that verbatim is
    useless to read and — before this was capped — broke the dialog's layout
    outright.
    """
    first_line = command.strip().splitlines()[0] if command.strip() else ""
    if len(first_line) > COMMAND_SUMMARY_CHARS:
        first_line = first_line[: COMMAND_SUMMARY_CHARS - 1].rstrip() + "…"
    elif "\n" in command.strip():
        first_line += " …"
    return first_line


class ProgressDialog(Adw.Dialog):
    """Streams command output for one install/uninstall action."""

    def __init__(self, action_title: str) -> None:
        super().__init__(title=action_title, content_width=640, content_height=440)
        self.set_can_close(False)

        self._spinner = Adw.Spinner()
        self._status_label = Gtk.Label(
            label="Working…", xalign=0, hexpand=True, css_classes=["title-4"]
        )
        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        status_row.append(self._spinner)
        status_row.append(self._status_label)

        # Hard-capped on purpose. A script entry's "command" is the whole
        # script — 150+ lines for the NAS one — and an uncapped wrapping label
        # grows to hundreds of lines, squashing the output view to nothing and
        # pushing the buttons off the bottom of a fixed-height dialog. The full
        # text is in the log; this is only ever a hint.
        self._detail_label = Gtk.Label(
            xalign=0,
            wrap=True,
            lines=2,
            ellipsize=Pango.EllipsizeMode.END,
            selectable=True,
            visible=False,
            css_classes=["dim-label", "caption"],
        )

        self._buffer = Gtk.TextBuffer()
        self._text_view = Gtk.TextView(
            buffer=self._buffer,
            editable=False,
            cursor_visible=False,
            monospace=True,
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
            top_margin=8,
            bottom_margin=8,
            left_margin=8,
            right_margin=8,
        )
        # min_content_height so the output can never be squeezed to nothing by
        # whatever else ends up in this box.
        scrolled = Gtk.ScrolledWindow(
            child=self._text_view,
            vexpand=True,
            hexpand=True,
            min_content_height=180,
            css_classes=["card"],
        )

        self._button_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            halign=Gtk.Align.END,
        )

        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        content.append(status_row)
        content.append(self._detail_label)
        content.append(scrolled)
        content.append(self._button_box)

        self._header = header = Adw.HeaderBar(
            show_start_title_buttons=False, show_end_title_buttons=False
        )
        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)
        toolbar_view.set_content(content)
        self.set_child(toolbar_view)

    def append_line(self, line: str) -> None:
        """Append one line of output and scroll to the bottom.

        Must be called from the GTK main loop (marshal with GLib.idle_add
        from worker threads — CLAUDE.md hard rule 3).
        """
        end = self._buffer.get_end_iter()
        self._buffer.insert(end, line + "\n")
        self._text_view.scroll_to_iter(self._buffer.get_end_iter(), 0.0, False, 0.0, 0.0)

    def _allow_closing(self) -> None:
        """Let the user out, by every route.

        The header close button is a deliberate belt-and-braces: if anything
        ever pushes the button row out of view again, Escape and the title-bar
        button both still work.
        """
        self.set_can_close(True)
        self._header.set_show_end_title_buttons(True)

    def finish_success(self) -> None:
        """Mark the action as complete and let the user close the dialog."""
        self._allow_closing()
        self._spinner.set_visible(False)
        self._status_label.set_label("Done")
        self._status_label.add_css_class("success")
        self._add_close_button(suggested=True)

    def finish_failure(self, result: CommandResult | None, message: str) -> None:
        """Show the failing command and offer the log. Never a bare failure."""
        self._allow_closing()
        self._spinner.set_visible(False)
        self._status_label.set_label(message)
        self._status_label.add_css_class("error")

        if result is not None:
            self._detail_label.set_label(
                f"{short_command(result.command)}  ·  exit code {result.returncode}"
            )
            self._detail_label.set_visible(True)
            # The output above may have scrolled past; the failure is almost
            # always at the end, so put the reader there.
            self.append_line("")
            self.append_line(f"[ignis] failed with exit code {result.returncode}")

        copy_button = Gtk.Button(label="Copy Log")
        copy_button.connect("clicked", self._on_copy_log)
        self._button_box.append(copy_button)

        open_button = Gtk.Button(label="Open Log Folder")
        open_button.connect("clicked", self._on_open_log_folder)
        self._button_box.append(open_button)

        self._add_close_button(suggested=False)

    def _add_close_button(self, *, suggested: bool) -> None:
        """Append the Close button, styled as the primary action on success."""
        button = Gtk.Button(label="Close")
        if suggested:
            button.add_css_class("suggested-action")
        button.connect("clicked", lambda _b: self.close())
        self._button_box.append(button)

    def _on_copy_log(self, _button: Gtk.Button) -> None:
        """Copy this dialog's full output to the clipboard."""
        start, end = self._buffer.get_bounds()
        text = self._buffer.get_text(start, end, include_hidden_chars=False)
        self.get_display().get_clipboard().set_text(text)

    def _on_open_log_folder(self, _button: Gtk.Button) -> None:
        """Open the folder containing ignis.log in the file manager."""
        open_log_folder(self)
