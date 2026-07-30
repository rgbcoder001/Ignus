"""Updates page: GitHub-sourced apps and the releases available for them.

Only GitHub-sourced apps appear here. Flathub and ujust apps are updated by
the system's own updater, which is the right place for them.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ignis.core.catalog import App, GithubSource
from ignis.core.host import HostBridge
from ignis.core.state import State
from ignis.providers import GithubReleaseProvider
from ignis.providers.base import InstallStatus, ProviderError
from ignis.views.actions import run_action
from ignis.views.common import open_log_folder

log = logging.getLogger(__name__)


def github_apps(apps: list[App]) -> list[App]:
    """The catalog entries installed from GitHub releases."""
    return [app for app in apps if isinstance(app.source, GithubSource)]


def pending_update_count(apps: list[App], bridge: HostBridge, state: State) -> int:
    """How many GitHub apps have a newer release cached. No network."""
    count = 0
    for app in github_apps(apps):
        provider = GithubReleaseProvider(app, bridge, state)
        if provider.status() is InstallStatus.UPDATE_AVAILABLE:
            count += 1
    return count


class _UpdateRow(Adw.ActionRow):
    """One GitHub app, with its installed and latest versions."""

    __gtype_name__ = "IgnisUpdateRow"

    def __init__(self, provider: GithubReleaseProvider, on_update: Callable[[GithubReleaseProvider], None]) -> None:
        super().__init__(title=provider.app.name)
        self.provider = provider
        self._on_update = on_update

        self.button = Gtk.Button(
            label="Update", css_classes=["suggested-action"], valign=Gtk.Align.CENTER, visible=False
        )
        self.button.connect("clicked", lambda _b: self._on_update(self.provider))
        self.add_suffix(self.button)
        self.refresh()

    def refresh(self, latest_tag: str | None = None) -> None:
        """Re-read state and show where this app stands."""
        installed = self.provider.installed_tag()
        status = self.provider.status()

        if installed is None:
            self.set_subtitle("Not installed")
            self.button.set_visible(False)
            return

        if latest_tag is None:
            cached = self.provider.client.cached_release(self.provider.source.repo)
            latest_tag = cached.tag if cached else None

        if status is InstallStatus.UPDATE_AVAILABLE and latest_tag:
            self.set_subtitle(f"{installed}  →  {latest_tag}")
            self.button.set_visible(True)
        else:
            self.set_subtitle(f"{installed} — up to date")
            self.button.set_visible(False)


class UpdatesPage(Adw.NavigationPage):
    """Lists GitHub-sourced apps and lets the user update them."""

    def __init__(
        self,
        apps: list[App],
        bridge: HostBridge,
        state: State,
        on_changed: Callable[[], None],
    ) -> None:
        super().__init__(title="Updates", tag="updates")
        self._bridge = bridge
        self._state = state
        self._on_changed = on_changed
        self._rows: list[_UpdateRow] = []

        entries = github_apps(apps)
        header = Adw.HeaderBar()
        self._refresh_button = Gtk.Button(
            icon_name="view-refresh-symbolic", tooltip_text="Check for updates"
        )
        self._refresh_button.connect("clicked", lambda _b: self.check_for_updates())
        header.pack_end(self._refresh_button)

        self._banner = Adw.Banner(revealed=False, button_label="Open Log Folder")
        self._banner.connect("button-clicked", lambda _b: open_log_folder(self))

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)
        toolbar_view.add_top_bar(self._banner)
        toolbar_view.set_content(self._build_content(entries))
        self.set_child(toolbar_view)

    def _build_content(self, entries: list[App]) -> Gtk.Widget:
        """A row per GitHub app, or an explanation when there are none."""
        if not entries:
            return Adw.StatusPage(
                icon_name="emblem-ok-symbolic",
                title="Nothing to update here",
                description=(
                    "Apps from Flathub and Bazzite recipes are updated by the "
                    "system itself. Only apps installed straight from GitHub "
                    "are listed on this page."
                ),
            )

        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="Installed from GitHub",
            description="Ignis downloads these directly from each project's releases.",
        )
        for app in entries:
            row = _UpdateRow(
                GithubReleaseProvider(app, self._bridge, self._state), self._start_update
            )
            self._rows.append(row)
            group.add(row)
        page.add(group)
        return page

    def check_for_updates(self) -> None:
        """Ask GitHub for the latest release of each app, off the main thread."""
        if not self._rows:
            return
        self._refresh_button.set_sensitive(False)
        self._banner.set_revealed(False)

        def worker() -> None:
            errors: list[str] = []
            results: list[tuple[_UpdateRow, str | None]] = []
            for row in self._rows:
                try:
                    release = row.provider.fetch_latest()
                except ProviderError as exc:
                    log.warning("update check failed for %s: %s", row.provider.app.id, exc)
                    errors.append(str(exc))
                    results.append((row, None))
                else:
                    results.append((row, release.tag))
            GLib.idle_add(self._apply_check, results, errors)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_check(
        self, results: list[tuple[_UpdateRow, str | None]], errors: list[str]
    ) -> bool:
        """Show the results of an update check. Runs on the main loop."""
        for row, tag in results:
            row.refresh(tag)
        self._refresh_button.set_sensitive(True)
        if errors:
            # Rule 4: a failed check is reported, never silently treated as
            # "everything is up to date".
            self._banner.set_title(errors[0])
            self._banner.set_revealed(True)
        self._on_changed()
        return GLib.SOURCE_REMOVE

    def _start_update(self, provider: GithubReleaseProvider) -> None:
        """Install the newer release for one app."""
        run_action(
            self,
            f"Updating {provider.app.name}",
            provider.run_install,
            on_done=self._after_update,
        )

    def _after_update(self) -> None:
        """Refresh every row after an update finishes."""
        for row in self._rows:
            row.refresh()
        self._on_changed()
