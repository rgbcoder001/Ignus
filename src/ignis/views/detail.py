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
from dataclasses import dataclass
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ignis.core import hardware, shortcuts
from ignis.core.catalog import App
from ignis.core.host import HostBridge
from ignis.core.state import State
from ignis.providers import Provider, UnsupportedSourceError, create_provider
from ignis.providers.base import InstallStatus, NotSupportedError, ProviderError
from ignis.views.actions import Action, run_action
from ignis.views.common import app_icon, hardware_badges
from ignis.views.setup import SetupDialog

log = logging.getLogger(__name__)

STATUS_LABELS = {
    InstallStatus.INSTALLED: "Installed",
    InstallStatus.NOT_INSTALLED: "Not installed",
    InstallStatus.UPDATE_AVAILABLE: "Update available",
    InstallStatus.UNKNOWN: "Status unknown",
}


@dataclass
class _Snapshot:
    """What one status check found, gathered off the main thread."""

    status: InstallStatus
    can_launch: bool = False
    desktop_dir: Path | None = None
    has_shortcut: bool = False


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
        self._state = state
        self._on_changed = on_changed
        self._provider: Provider | None = None
        self._unsupported_reason: str | None = None
        self._desktop_dir: Path | None = None
        self._suppress_shortcut_toggle = False

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
            self._shortcut_row = Adw.SwitchRow(
                title="Put a shortcut on the desktop",
                subtitle="Adds an icon you can double-click",
                sensitive=False,
            )
            self._shortcut_row.connect("notify::active", self._on_shortcut_toggled)
            shortcut_group = Adw.PreferencesGroup()
            shortcut_group.add(self._shortcut_row)
            page.add(shortcut_group)

            actions_group = Adw.PreferencesGroup()
            self._launch_button = Gtk.Button(
                label="Open", css_classes=["pill"], halign=Gtk.Align.CENTER, visible=False
            )
            self._launch_button.connect("clicked", self._on_launch_clicked)
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
            button_row.append(self._launch_button)
            button_row.append(self._install_button)
            button_row.append(self._uninstall_button)
            actions_group.add(button_row)
            page.add(actions_group)

        return page

    def _start_status_check(self) -> None:
        """Query status, launchability and shortcut state off the main thread."""
        self._status_spinner.set_visible(True)
        self._status_row.set_subtitle("Checking…")

        def worker() -> None:
            status = self._provider.status()
            snapshot = _Snapshot(status=status)
            if status in (InstallStatus.INSTALLED, InstallStatus.UPDATE_AVAILABLE):
                snapshot.can_launch = self._provider.launch_command() is not None
                if self._provider.shortcut_entry() is not None:
                    snapshot.desktop_dir = shortcuts.desktop_dir(self._bridge)
                    snapshot.has_shortcut = shortcuts.has_shortcut(
                        snapshot.desktop_dir, self._app.id
                    )
            GLib.idle_add(self._apply_status, snapshot)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_snapshot_extras(self, snapshot: _Snapshot) -> None:
        """Reflect launch and shortcut availability. Main loop only."""
        self._launch_button.set_visible(snapshot.can_launch)
        self._desktop_dir = snapshot.desktop_dir

        self._shortcut_row.set_sensitive(snapshot.desktop_dir is not None)
        # Setting the switch fires notify::active, which would otherwise be
        # mistaken for the user toggling it.
        self._suppress_shortcut_toggle = True
        self._shortcut_row.set_active(snapshot.has_shortcut)
        self._suppress_shortcut_toggle = False

    def _on_launch_clicked(self, _button: Gtk.Button) -> None:
        """Start the installed app."""
        try:
            self._provider.launch()
        except ProviderError as exc:
            log.error("could not open %s: %s", self._app.id, exc)
            self._toast(str(exc))

    def _on_shortcut_toggled(self, row: Adw.SwitchRow, _param) -> None:
        """Create or remove the desktop shortcut."""
        if self._suppress_shortcut_toggle or self._desktop_dir is None:
            return
        try:
            if row.get_active():
                entry = self._provider.shortcut_entry()
                if entry is None:
                    raise NotSupportedError(f"No shortcut available for {self._app.name}")
                shortcuts.create_shortcut(
                    self._desktop_dir, self._app.id, entry, self._bridge
                )
                self._toast("Shortcut added to your desktop")
            else:
                shortcuts.remove_shortcut(self._desktop_dir, self._app.id)
                self._toast("Shortcut removed")
        except (ProviderError, OSError) as exc:
            log.exception("could not change the desktop shortcut for %s", self._app.id)
            self._toast(f"Could not change the shortcut: {exc}")
            self._suppress_shortcut_toggle = True
            row.set_active(not row.get_active())
            self._suppress_shortcut_toggle = False

    def _toast(self, message: str) -> None:
        """Show a brief message if the window can display one."""
        window = self.get_root()
        add_toast = getattr(window, "add_toast", None)
        if callable(add_toast):
            add_toast(Adw.Toast(title=message))
        else:
            log.info("%s", message)

    def _apply_status(self, snapshot: _Snapshot) -> bool:
        """Update the status row and buttons. Runs on the main loop.

        Re-runs after every install/uninstall, so each control is set both
        ways — hiding the spinner rather than removing it (removing twice
        warns), and explicitly toggling Uninstall so it disappears again
        once the app is gone.
        """
        status = snapshot.status
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
        self._apply_snapshot_extras(snapshot)
        self._on_changed(self._app.id, status)
        return GLib.SOURCE_REMOVE

    def _on_install_clicked(self, _button: Gtk.Button) -> None:
        verb = "Updating" if self._install_button.get_label() == "Update" else "Installing"
        title = f"{verb} {self._app.name}"

        if self._app.settings:
            # Ask first, then install with the answers saved.
            SetupDialog(
                self._app,
                self._state.app_settings(self._app.id),
                lambda values: self._save_and_install(values, title),
            ).present(self)
            return

        self._run_action(title, self._provider.run_install)

    def _save_and_install(self, values: dict[str, str], title: str) -> None:
        """Store the setup answers, then install. Runs on the main loop."""
        self._state.set_app_settings(self._app.id, values)
        try:
            self._state.save()
        except OSError:
            log.exception("could not save setup answers for %s", self._app.id)
            self._toast("Could not save those details — see the log")
            return
        self._run_action(title, self._provider.run_install)

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
