"""Per-app detail page: description, source, and install/uninstall controls.

Pushed onto the main window's Adw.NavigationView (SPEC.md §5). Runs the
provider's action in a worker thread behind a ProgressDialog, then reports
the new status back to the caller via ``on_changed`` so the Browse row stays
in sync (CLAUDE.md hard rule 3: never block the GTK main loop).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ignis.core import hardware
from ignis.core.catalog import App
from ignis.core.host import HostBridge
from ignis.core.state import State
from ignis.providers import Provider, UnsupportedSourceError, create_provider
from ignis.providers.base import InstallStatus
from ignis.views.actions import Action, run_action
from ignis.views.common import app_icon, hardware_badges

log = logging.getLogger(__name__)

STATUS_LABELS = {
    InstallStatus.INSTALLED: "Installed",
    InstallStatus.NOT_INSTALLED: "Not installed",
    InstallStatus.UPDATE_AVAILABLE: "Update available",
    InstallStatus.UNKNOWN: "Status unknown",
}


class DetailPage(Adw.NavigationPage):
    """Full detail view for one catalog app."""

    def __init__(
        self,
        app: App,
        bridge: HostBridge,
        state: State,
        vendors: frozenset[str],
        on_changed: Callable[[str, InstallStatus], None],
    ) -> None:
        super().__init__(title=app.name, tag=f"detail-{app.id}")
        self._app = app
        self._bridge = bridge
        self._on_changed = on_changed
        self._provider: Provider | None = None
        self._unsupported_reason: str | None = None

        try:
            self._provider = create_provider(app, bridge, state)
        except UnsupportedSourceError as exc:
            self._unsupported_reason = str(exc)

        # A header bar (even an empty one) is what lets Adw.NavigationView
        # inject the back button and display this page's title.
        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())
        toolbar_view.set_content(self._build_content(vendors))
        self.set_child(toolbar_view)

        if self._provider is not None:
            self._start_status_check()

    def _build_content(self, vendors: frozenset[str]) -> Gtk.Widget:
        """Header info, hardware note, source/command transparency, actions."""
        page = Adw.PreferencesPage()

        header_group = Adw.PreferencesGroup()
        header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        header_box.append(app_icon(self._app, 64))
        header_box.append(Gtk.Label(label=self._app.name, css_classes=["title-1"], wrap=True))
        if self._app.description:
            header_box.append(
                Gtk.Label(
                    label=self._app.description,
                    wrap=True,
                    justify=Gtk.Justification.CENTER,
                    css_classes=["dim-label"],
                )
            )
        header_box.set_halign(Gtk.Align.CENTER)
        header_group.add(header_box)
        page.add(header_group)

        info_group = Adw.PreferencesGroup(title="About this app")
        if self._unsupported_reason:
            info_group.add(
                Adw.ActionRow(title="Not yet supported", subtitle=self._unsupported_reason)
            )
        else:
            info_group.add(
                Adw.ActionRow(title="Source", subtitle=self._provider.describe_source())
            )
            command_row = Adw.ExpanderRow(title="Command that will run")
            command_row.add_row(
                Adw.ActionRow(
                    subtitle=self._provider.command_preview(),
                    subtitle_selectable=True,
                    css_classes=["property"],
                )
            )
            info_group.add(command_row)

            self._status_row = Adw.ActionRow(title="Status", subtitle="Checking…")
            self._status_spinner = Adw.Spinner()
            self._status_row.add_suffix(self._status_spinner)
            info_group.add(self._status_row)

        if self._app.hardware:
            hardware_row = Adw.ActionRow(
                title="Hardware",
                subtitle=" ".join(
                    hardware.badge_tooltip(v, hardware.badge_state(v, vendors))
                    for v in sorted(self._app.hardware)
                ),
            )
            for vendor_badge in hardware_badges(self._app, vendors):
                hardware_row.add_suffix(vendor_badge)
            info_group.add(hardware_row)
        page.add(info_group)

        if self._provider is not None:
            actions_group = Adw.PreferencesGroup()
            self._install_button = Gtk.Button(
                label="Install", css_classes=["suggested-action", "pill"], halign=Gtk.Align.CENTER
            )
            self._install_button.connect("clicked", self._on_install_clicked)
            self._uninstall_button = Gtk.Button(
                label="Uninstall", css_classes=["destructive-action", "pill"], halign=Gtk.Align.CENTER
            )
            self._uninstall_button.connect("clicked", self._on_uninstall_clicked)
            self._uninstall_button.set_visible(False)
            button_row = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL, spacing=12, halign=Gtk.Align.CENTER
            )
            button_row.append(self._install_button)
            button_row.append(self._uninstall_button)
            actions_group.add(button_row)
            page.add(actions_group)

        return page

    def _start_status_check(self) -> None:
        """Query provider status off the main thread."""
        self._status_spinner.set_visible(True)
        self._status_row.set_subtitle("Checking…")

        def worker() -> None:
            status = self._provider.status()
            GLib.idle_add(self._apply_status, status)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_status(self, status: InstallStatus) -> bool:
        """Update the status row and buttons. Runs on the main loop.

        Re-runs after every install/uninstall, so each control is set both
        ways — hiding the spinner rather than removing it (removing twice
        warns), and explicitly toggling Uninstall so it disappears again
        once the app is gone.
        """
        self._status_spinner.set_visible(False)
        self._status_row.set_subtitle(STATUS_LABELS[status])

        self._install_button.set_sensitive(True)
        self._install_button.set_label(
            "Update" if status is InstallStatus.UPDATE_AVAILABLE else "Install"
        )
        self._uninstall_button.set_visible(
            self._provider.supports_uninstall
            and status in (InstallStatus.INSTALLED, InstallStatus.UPDATE_AVAILABLE)
        )
        self._on_changed(self._app.id, status)
        return GLib.SOURCE_REMOVE

    def _on_install_clicked(self, _button: Gtk.Button) -> None:
        verb = "Updating" if self._install_button.get_label() == "Update" else "Installing"
        self._run_action(f"{verb} {self._app.name}", self._provider.run_install)

    def _on_uninstall_clicked(self, _button: Gtk.Button) -> None:
        self._run_action(f"Uninstalling {self._app.name}", self._provider.uninstall)

    def _run_action(self, title: str, action: Action) -> None:
        """Run a provider action behind a ProgressDialog, off the main thread."""
        self._install_button.set_sensitive(False)
        self._uninstall_button.set_sensitive(False)
        run_action(self, title, action, on_done=self._after_action)

    def _after_action(self) -> None:
        """Re-enable controls and re-check status. Runs on the main loop."""
        self._install_button.set_sensitive(True)
        self._uninstall_button.set_sensitive(True)
        self._start_status_check()
