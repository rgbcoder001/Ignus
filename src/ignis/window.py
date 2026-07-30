"""Main window: owns the Adw.NavigationView the pages are pushed onto.

Browse is the root page; Detail, Updates and Settings push on top of it.
SPEC.md §5 sketches a ViewStack + ViewSwitcher for the top-level sections —
this uses one navigation stack with header buttons instead, which keeps a
single, already-exercised navigation mechanism rather than adding a second
one that has never been run (see the Phase 2 note in SPEC.md §5).
"""

from __future__ import annotations

import logging
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib  # noqa: E402

from ignis import APP_NAME
from ignis.core import paths
from ignis.core.catalog import App
from ignis.core.host import HostBridge
from ignis.core.state import State
from ignis.providers.base import InstallStatus
from ignis.views.browse import BrowseView
from ignis.views.detail import DetailPage
from ignis.views.settings import SettingsPage
from ignis.views.updates import UpdatesPage, pending_update_count

log = logging.getLogger(__name__)


class IgnisWindow(Adw.ApplicationWindow):
    """Hosts the navigation stack; owns the shared State and HostBridge."""

    def __init__(
        self,
        application: Adw.Application,
        apps: list[App],
        bridge: HostBridge,
        vendors: frozenset[str],
    ) -> None:
        super().__init__(application=application, title=APP_NAME)
        self._apps = apps
        self._bridge = bridge
        self._vendors = vendors
        self._state = State.load(paths.state_file())

        width, height, maximized = self._state.window_geometry()
        self.set_default_size(width, height)
        if maximized:
            self.maximize()
        self.connect("close-request", self._on_close_request)

        self._nav_view = Adw.NavigationView()
        self._browse = BrowseView(
            apps,
            bridge,
            self._state,
            vendors,
            self._open_detail,
            self._open_updates,
            self._open_settings,
        )
        self._nav_view.push(self._browse)

        self._toasts = Adw.ToastOverlay(child=self._nav_view)
        self.set_content(self._toasts)

        self._refresh_update_count()

    def add_toast(self, toast: Adw.Toast) -> None:
        """Show a transient message. Used by the Settings page."""
        self._toasts.add_toast(toast)

    def _open_detail(self, app: App) -> None:
        """Push the detail page for ``app``."""
        page = DetailPage(
            app, self._bridge, self._state, self._vendors, self._on_status_changed
        )
        self._nav_view.push(page)

    def _open_updates(self) -> None:
        """Push the Updates page and immediately check for new releases."""
        page = UpdatesPage(self._apps, self._bridge, self._state, self._refresh_update_count)
        self._nav_view.push(page)
        page.check_for_updates()

    def _open_settings(self) -> None:
        """Push the Settings page."""
        self._nav_view.push(
            SettingsPage(self._state, self._bridge, self._vendors, len(self._apps))
        )

    def _on_close_request(self, *_args) -> bool:
        """Remember the window size before closing. Never blocks the close.

        GTK4 keeps default-width/default-height in step with the current
        size, so they are what should be persisted.
        """
        try:
            width, height = self.get_default_size()
            self._state.set_window_geometry(width, height, self.is_maximized())
            self._state.save()
        except OSError:
            log.warning("could not save the window size", exc_info=True)
        return False

    def _on_status_changed(self, app_id: str, status: InstallStatus) -> None:
        """Keep Browse's status pill and the updates badge in sync."""
        self._browse.refresh_row(app_id, status)
        self._refresh_update_count()

    def _refresh_update_count(self) -> None:
        """Recount pending updates off the main thread (it reads the cache)."""

        def worker() -> None:
            count = pending_update_count(self._apps, self._bridge, self._state)
            GLib.idle_add(self._apply_update_count, count)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_update_count(self, count: int) -> bool:
        """Show the pending-update count on Browse. Runs on the main loop."""
        self._browse.set_update_count(count)
        return GLib.SOURCE_REMOVE
