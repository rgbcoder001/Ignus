"""Browse view: the catalog, filterable by category, as a boxed list.

SPEC.md §5 describes a FlowBox grid of cards. This ships a Gtk.ListBox of
Adw.ActionRow instead — the same information (icon, name, summary, hardware
badges, status pill, click-through to detail) with far less new/unverified
GTK API surface, which matters because this code has never been run: there is
no way to render GTK from the Windows dev machine used to write it. A
card-grid upgrade is a reasonable Phase 4 (UI polish) candidate once someone
can actually see it on screen.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ignis import APP_ID, APP_NAME, __version__
from ignis.core import paths
from ignis.core.catalog import App, Category
from ignis.core.host import HostBridge
from ignis.core.state import State
from ignis.providers import UnsupportedSourceError, create_provider
from ignis.providers.base import InstallStatus
from ignis.views.common import app_icon, badge, hardware_badges, open_log_folder

log = logging.getLogger(__name__)

CATEGORY_TITLES = {
    Category.GAMING: "Gaming",
    Category.EMULATION: "Emulation",
    Category.MEDIA: "Media",
    Category.STREAMING: "Streaming",
    Category.SYSTEM: "System",
}

PILL_LABELS = {
    InstallStatus.INSTALLED: "Installed",
    InstallStatus.UPDATE_AVAILABLE: "Update available",
}

PILL_STYLES = {
    InstallStatus.INSTALLED: "success",
    InstallStatus.UPDATE_AVAILABLE: "accent",
}


class AppRow(Adw.ActionRow):
    """One catalog row, holding a reference to the App it represents.

    A real subclass rather than a Python attribute stashed on a plain
    Adw.ActionRow: PyGObject only guarantees Python state survives on
    instances of Python-defined subclasses, where the Python object *is* the
    GObject. Attributes set on a wrapper around a native instance can be lost
    if that wrapper is collected and later recreated from C — which is exactly
    what happens when GTK hands a row back to a filter callback.
    """

    __gtype_name__ = "IgnisAppRow"

    def __init__(self, app: App, vendors: frozenset[str], supported: bool) -> None:
        super().__init__(title=app.name, subtitle=app.summary, activatable=True)
        self.app = app

        self.add_prefix(app_icon(app, 32))
        for vendor_badge in hardware_badges(app, vendors):
            self.add_suffix(vendor_badge)

        self.spinner = Adw.Spinner()
        self.pill = Gtk.Label(visible=False, valign=Gtk.Align.CENTER)
        self.add_suffix(self.spinner)
        self.add_suffix(self.pill)

        if not supported:
            self.spinner.set_visible(False)
            self.add_suffix(
                badge(
                    "Not yet supported",
                    tooltip="Ignis can't install this kind of app yet.",
                )
            )

    def show_status(self, status: InstallStatus) -> None:
        """Update this row's status pill."""
        self.spinner.set_visible(False)
        label = PILL_LABELS.get(status)
        if label is None:
            self.pill.set_visible(False)
            return
        self.pill.set_label(label)
        self.pill.set_css_classes(["caption", PILL_STYLES[status]])
        self.pill.set_visible(True)


class BrowseView(Adw.NavigationPage):
    """Root page: category filter chips over a filterable list of apps."""

    def __init__(
        self,
        apps: list[App],
        bridge: HostBridge,
        state: State,
        vendors: frozenset[str],
        on_open_detail: Callable[[App], None],
        on_open_updates: Callable[[], None],
        on_open_settings: Callable[[], None],
    ) -> None:
        super().__init__(title=APP_NAME, tag="browse")
        self._apps = apps
        self._bridge = bridge
        self._state = state
        self._vendors = vendors
        self._on_open_detail = on_open_detail
        self._on_open_updates = on_open_updates
        self._on_open_settings = on_open_settings
        self._selected_category: Category | None = None
        self._rows: dict[str, AppRow] = {}
        self._list_box: Gtk.ListBox | None = None

        if apps:
            content = self._build_catalog_page(apps)
        else:
            # Rule 4: never a silently empty screen — and never a dead end
            # either, so the log is one click away.
            content = Adw.StatusPage(
                icon_name="dialog-warning-symbolic",
                title="No apps available",
                description=(
                    f"The catalog at {paths.catalog_path()} could not be loaded, "
                    "so there is nothing to show. The log says why."
                ),
                child=Gtk.Button(
                    label="Open Log Folder",
                    halign=Gtk.Align.CENTER,
                    css_classes=["pill", "suggested-action"],
                ),
            )
            content.get_child().connect("clicked", lambda _b: open_log_folder(self))

        # Each Adw.NavigationPage carries its own header bar — that's how
        # Adw.NavigationView knows where to inject the back button on
        # sub-pages, and it reads this page's title automatically.
        header = Adw.HeaderBar()

        self._updates_button = Gtk.Button(
            icon_name="software-update-available-symbolic",
            tooltip_text="Updates",
        )
        self._updates_button.connect("clicked", lambda _b: self._on_open_updates())
        header.pack_end(self._updates_button)

        settings_button = Gtk.Button(
            icon_name="emblem-system-symbolic", tooltip_text="Settings"
        )
        settings_button.connect("clicked", lambda _b: self._on_open_settings())
        header.pack_end(settings_button)

        about_button = Gtk.Button(
            icon_name="help-about-symbolic", tooltip_text="About Ignis"
        )
        about_button.connect("clicked", self._on_about)
        header.pack_end(about_button)

        self._host_banner = Adw.Banner(
            title="Checking system access…", revealed=False, button_label="Open Log Folder"
        )
        self._host_banner.connect("button-clicked", lambda _b: open_log_folder(self))

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)
        toolbar_view.add_top_bar(self._host_banner)
        toolbar_view.set_content(content)
        self.set_child(toolbar_view)

        self._start_host_check()
        self._start_status_checks()

    def _build_catalog_page(self, apps: list[App]) -> Gtk.Widget:
        """The filter chips plus the (filterable) boxed list of app rows."""
        self._list_box = Gtk.ListBox(
            css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE
        )
        self._list_box.set_filter_func(self._filter_row)
        for app in apps:
            self._list_box.append(self._build_row(app))

        page = Adw.PreferencesPage()
        filter_group = Adw.PreferencesGroup()
        filter_group.add(self._build_category_filter())
        page.add(filter_group)

        list_group = Adw.PreferencesGroup(title="Apps")
        list_group.add(self._list_box)
        page.add(list_group)
        return page

    def _build_row(self, app: App) -> AppRow:
        """Build one app row, marking it unsupported if it has no provider."""
        try:
            create_provider(app, self._bridge, self._state)
        except UnsupportedSourceError:
            supported = False
        else:
            supported = True

        row = AppRow(app, self._vendors, supported)
        row.connect("activated", lambda _r, a=app: self._on_open_detail(a))
        self._rows[app.id] = row
        return row

    def _build_category_filter(self) -> Gtk.Widget:
        """Filter chips: All, plus one per category present in the catalog."""
        box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=0,
            halign=Gtk.Align.CENTER,
            css_classes=["linked"],
        )
        present = {app.category for app in self._apps}

        all_button = Gtk.ToggleButton(label="All", active=True)
        all_button.connect("toggled", self._on_category_toggled, None)
        box.append(all_button)

        for category in Category:
            if category not in present:
                continue
            button = Gtk.ToggleButton(label=CATEGORY_TITLES[category])
            button.set_group(all_button)
            button.connect("toggled", self._on_category_toggled, category)
            box.append(button)

        return box

    def _on_category_toggled(self, button: Gtk.ToggleButton, category: Category | None) -> None:
        if button.get_active():
            self._selected_category = category
            if self._list_box is not None:
                self._list_box.invalidate_filter()

    def _filter_row(self, row: AppRow) -> bool:
        if self._selected_category is None:
            return True
        return row.app.category is self._selected_category

    def _start_host_check(self) -> None:
        """Run once at startup: if HostBridge itself is broken, say so loudly
        instead of letting every app silently read as 'not installed'."""

        def worker() -> None:
            result = self._bridge.run(["flatpak", "--version"], check=False, timeout=15)
            if not result.ok:
                GLib.idle_add(self._show_host_banner, result.tail(1))

        threading.Thread(target=worker, daemon=True).start()

    def _show_host_banner(self, detail: str) -> bool:
        """Reveal the host-access warning banner. Runs on the main loop."""
        self._host_banner.set_title(f"Can't run commands on your system: {detail}")
        self._host_banner.set_revealed(True)
        return GLib.SOURCE_REMOVE

    def _start_status_checks(self) -> None:
        """Probe every supported app's status off the main thread, one by one."""

        def worker() -> None:
            for app in self._apps:
                try:
                    provider = create_provider(app, self._bridge, self._state)
                except UnsupportedSourceError:
                    continue
                status = provider.status()
                GLib.idle_add(self.refresh_row, app.id, status)

        threading.Thread(target=worker, daemon=True).start()

    def refresh_row(self, app_id: str, status: InstallStatus) -> bool:
        """Update one row's status pill. Main loop only."""
        row = self._rows.get(app_id)
        if row is not None:
            row.show_status(status)
        return GLib.SOURCE_REMOVE

    def set_update_count(self, count: int) -> None:
        """Reflect pending updates in the header's Updates button tooltip."""
        self._updates_button.set_tooltip_text(
            f"Updates ({count} available)" if count else "Updates"
        )
        if count:
            self._updates_button.add_css_class("suggested-action")
        else:
            self._updates_button.remove_css_class("suggested-action")

    def _on_about(self, _button: Gtk.Button) -> None:
        """Show the about dialog."""
        Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            version=__version__,
            comments="One-stop app installer for Bazzite.",
            website="https://github.com/rgbcoder001/ignis",
            issue_url="https://github.com/rgbcoder001/ignis/issues",
            license_type=Gtk.License.MIT_X11,
        ).present(self)


