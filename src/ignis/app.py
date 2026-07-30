"""The Adw.Application subclass."""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio  # noqa: E402

from ignis import APP_ID
from ignis.core.catalog import App
from ignis.core.host import HostBridge
from ignis.window import IgnisWindow

log = logging.getLogger(__name__)


class IgnisApplication(Adw.Application):
    """Application object owning the main window."""

    def __init__(
        self, apps: list[App], bridge: HostBridge, vendors: frozenset[str]
    ) -> None:
        super().__init__(
            application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS
        )
        self._apps = apps
        self._bridge = bridge
        self._vendors = vendors

    def do_activate(self) -> None:
        """Present the main window, creating it on first activation."""
        window = self.props.active_window
        if window is None:
            window = IgnisWindow(
                application=self,
                apps=self._apps,
                bridge=self._bridge,
                vendors=self._vendors,
            )
        window.present()
