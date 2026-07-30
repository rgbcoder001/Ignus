"""Settings page: GitHub token, system diagnostics and troubleshooting."""

from __future__ import annotations

import logging
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ignis import __version__
from ignis.core import hardware, paths
from ignis.core.host import HostBridge
from ignis.core.state import State
from ignis.views.common import open_log_folder

log = logging.getLogger(__name__)

TOKEN_HELP = (
    "Optional. Ignis checks GitHub for new versions of apps installed from "
    "GitHub releases. Without a token GitHub allows about 60 checks an hour "
    "for your whole network, which is usually plenty — add one only if you "
    "see rate-limit messages. A token with no permissions ticked is enough."
)


class SettingsPage(Adw.NavigationPage):
    """Token storage, system diagnostics, and a route to the log."""

    def __init__(
        self, state: State, bridge: HostBridge, vendors: frozenset[str], app_count: int
    ) -> None:
        super().__init__(title="Settings", tag="settings")
        self._state = state
        self._bridge = bridge

        page = Adw.PreferencesPage()
        page.add(self._build_github_group())
        page.add(self._build_system_group(vendors, app_count))
        page.add(self._build_troubleshooting_group())

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())
        toolbar_view.set_content(page)
        self.set_child(toolbar_view)

        self._start_host_check()

    def _build_github_group(self) -> Adw.PreferencesGroup:
        """The personal access token row."""
        group = Adw.PreferencesGroup(title="GitHub", description=TOKEN_HELP)
        self._token_row = Adw.PasswordEntryRow(
            title="Personal access token", show_apply_button=True
        )
        self._token_row.set_text(self._state.github_pat)
        self._token_row.connect("apply", self._on_token_applied)
        group.add(self._token_row)
        return group

    def _build_system_group(
        self, vendors: frozenset[str], app_count: int
    ) -> Adw.PreferencesGroup:
        """What Ignis detected about this machine — the first thing to check
        when something behaves unexpectedly."""
        group = Adw.PreferencesGroup(title="System")

        detected = ", ".join(hardware.label(v) for v in sorted(vendors))
        group.add(
            Adw.ActionRow(
                title="Graphics",
                subtitle=detected or "Not detected — every app is shown",
                css_classes=["property"],
            )
        )
        mode = "Flatpak" if HostBridge.in_flatpak() else "Development checkout"
        group.add(
            Adw.ActionRow(
                title="Running as",
                subtitle=f"{mode} · Ignis {__version__} · {app_count} apps in catalog",
                css_classes=["property"],
            )
        )

        self._host_row = Adw.ActionRow(
            title="System access", subtitle="Checking…", css_classes=["property"]
        )
        self._host_spinner = Adw.Spinner()
        self._host_row.add_suffix(self._host_spinner)
        group.add(self._host_row)
        return group

    def _build_troubleshooting_group(self) -> Adw.PreferencesGroup:
        """Where the log lives, and a button to open it."""
        group = Adw.PreferencesGroup(
            title="Troubleshooting",
            description=(
                "Every command Ignis runs is written to the log with its exit "
                "code and full output. Include it when reporting a problem."
            ),
        )
        row = Adw.ActionRow(
            title="Log file",
            subtitle=str(paths.log_file()),
            subtitle_selectable=True,
            css_classes=["property"],
        )
        open_button = Gtk.Button(label="Open Folder", valign=Gtk.Align.CENTER)
        open_button.connect("clicked", lambda _b: open_log_folder(self))
        row.add_suffix(open_button)
        group.add(row)
        return group

    def _start_host_check(self) -> None:
        """Confirm Ignis can run commands on the host, off the main thread."""

        def worker() -> None:
            result = self._bridge.run(["flatpak", "--version"], check=False, timeout=15)
            GLib.idle_add(self._apply_host_check, result)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_host_check(self, result) -> bool:
        """Show the host-access result. Runs on the main loop."""
        self._host_spinner.set_visible(False)
        if result.ok:
            first_line = result.output.strip().splitlines()
            self._host_row.set_subtitle(
                f"Working — {first_line[0]}" if first_line else "Working"
            )
        else:
            self._host_row.set_subtitle(
                f"Not working: {result.command} exited {result.returncode}"
            )
            self._host_row.add_css_class("error")
        return GLib.SOURCE_REMOVE

    def _on_token_applied(self, row: Adw.PasswordEntryRow) -> None:
        """Persist the token. A save failure must be visible, not silent."""
        self._state.github_pat = row.get_text()
        try:
            self._state.save()
        except OSError:
            log.exception("could not save the GitHub token")
            self._show_toast("Could not save the token — see the log")
            return
        self._show_toast("Token saved" if row.get_text().strip() else "Token cleared")

    def _show_toast(self, message: str) -> None:
        """Surface a short confirmation if a toast overlay is available."""
        window = self.get_root()
        add_toast = getattr(window, "add_toast", None)
        if callable(add_toast):
            add_toast(Adw.Toast(title=message))
        else:
            log.info("%s", message)
