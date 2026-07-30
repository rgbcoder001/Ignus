"""Updates page: Ignis itself, plus everything it installed.

Update checks talk to the network, so they only run behind an explicit
refresh — never from a status() call that the catalog list waits on.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ignis import APP_NAME
from ignis.core.catalog import App, FlathubSource, GithubSource
from ignis.core.host import HostBridge
from ignis.core.selfupdate import SelfUpdater
from ignis.core.state import State
from ignis.providers import GithubReleaseProvider
from ignis.providers.base import InstallStatus, ProviderError
from ignis.providers.flathub import FlathubProvider, updatable_refs
from ignis.views.actions import run_action
from ignis.views.common import open_log_folder

log = logging.getLogger(__name__)


def github_apps(apps: list[App]) -> list[App]:
    """Catalog entries installed from GitHub releases."""
    return [app for app in apps if isinstance(app.source, GithubSource)]


def flathub_apps(apps: list[App]) -> list[App]:
    """Catalog entries installed from Flathub."""
    return [app for app in apps if isinstance(app.source, FlathubSource)]


def pending_update_count(apps: list[App], bridge: HostBridge, state: State) -> int:
    """Updates known from cache alone, for the header badge. No network."""
    count = sum(
        1
        for app in github_apps(apps)
        if GithubReleaseProvider(app, bridge, state).status()
        is InstallStatus.UPDATE_AVAILABLE
    )
    if SelfUpdater(bridge, state).cached_update():
        count += 1
    return count


@dataclass
class CheckResult:
    """Everything one refresh discovered."""

    github: dict[str, str | None]
    flathub: frozenset[str]
    ignis: str | None = None
    errors: tuple[str, ...] = ()


class _SelfUpdateRow(Adw.ActionRow):
    """Ignis's own version, and the update button for it."""

    __gtype_name__ = "IgnisSelfUpdateRow"

    def __init__(self, updater: SelfUpdater, on_update: Callable[[], None]) -> None:
        super().__init__(title=APP_NAME)
        self.updater = updater
        self.button = Gtk.Button(
            label="Update",
            css_classes=["suggested-action"],
            valign=Gtk.Align.CENTER,
            visible=False,
        )
        self.button.connect("clicked", lambda _b: on_update())
        self.add_suffix(self.button)
        self.show_available(updater.cached_update())

    def show_available(self, tag: str | None) -> None:
        """Reflect whether a newer Ignis exists."""
        current = self.updater.current_version
        if tag:
            self.set_subtitle(f"{current}  →  {tag}")
            self.button.set_visible(True)
        else:
            self.set_subtitle(f"{current} — up to date")
            self.button.set_visible(False)


class _AppUpdateRow(Adw.ActionRow):
    """One catalog app on the updates list."""

    __gtype_name__ = "IgnisAppUpdateRow"

    def __init__(self, app: App, on_update: Callable[[_AppUpdateRow], None]) -> None:
        super().__init__(title=app.name)
        self.app = app
        self.button = Gtk.Button(
            label="Update",
            css_classes=["suggested-action"],
            valign=Gtk.Align.CENTER,
            visible=False,
        )
        self.button.connect("clicked", lambda _b: on_update(self))
        self.add_suffix(self.button)

    def show(self, subtitle: str, *, updatable: bool, visible: bool = True) -> None:
        """Set this row's state in one call."""
        self.set_subtitle(subtitle)
        self.button.set_visible(updatable)
        self.set_visible(visible)


class UpdatesPage(Adw.NavigationPage):
    """Lists available updates and applies them."""

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
        self._updater = SelfUpdater(bridge, state)
        self._github_rows: list[_AppUpdateRow] = []
        self._flathub_rows: list[_AppUpdateRow] = []

        header = Adw.HeaderBar()
        self._refresh_button = Gtk.Button(
            icon_name="view-refresh-symbolic", tooltip_text="Check for updates"
        )
        self._refresh_button.connect("clicked", lambda _b: self.check_for_updates())
        header.pack_end(self._refresh_button)

        self._banner = Adw.Banner(revealed=False, button_label="Open Log Folder")
        self._banner.connect("button-clicked", lambda _b: open_log_folder(self))

        self._spinner = Adw.Spinner(visible=False)
        header.pack_start(self._spinner)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)
        toolbar_view.add_top_bar(self._banner)
        toolbar_view.set_content(self._build_content(apps))
        self.set_child(toolbar_view)

    def _build_content(self, apps: list[App]) -> Gtk.Widget:
        """Ignis itself, then each source's apps."""
        page = Adw.PreferencesPage()

        ignis_group = Adw.PreferencesGroup(
            title="Ignis",
            description=(
                "Ignis is installed from a downloaded file, so it can't update "
                "itself through the software store."
            ),
        )
        self._self_row = _SelfUpdateRow(self._updater, self._start_self_update)
        ignis_group.add(self._self_row)
        page.add(ignis_group)

        github = github_apps(apps)
        if github:
            group = Adw.PreferencesGroup(
                title="Installed from GitHub",
                description="Ignis downloads these directly from each project's releases.",
            )
            for app in github:
                row = _AppUpdateRow(app, self._start_app_update)
                row.show("Checking…", updatable=False)
                self._github_rows.append(row)
                group.add(row)
            page.add(group)

        flathub = flathub_apps(apps)
        if flathub:
            group = Adw.PreferencesGroup(
                title="Installed from Flathub",
                description=(
                    "Your system usually updates these on its own; you can also "
                    "do it here."
                ),
            )
            for app in flathub:
                row = _AppUpdateRow(app, self._start_app_update)
                row.show("Checking…", updatable=False, visible=False)
                self._flathub_rows.append(row)
                group.add(row)
            page.add(group)

        return page

    def check_for_updates(self) -> None:
        """Refresh everything off the main thread."""
        self._refresh_button.set_sensitive(False)
        self._spinner.set_visible(True)
        self._banner.set_revealed(False)

        def worker() -> None:
            GLib.idle_add(self._apply_check, self._collect())

        threading.Thread(target=worker, daemon=True).start()

    def _collect(self) -> CheckResult:
        """Query GitHub and flatpak. Runs on a worker thread."""
        errors: list[str] = []

        ignis_tag = None
        try:
            ignis_tag = self._updater.available_update()
        except ProviderError as exc:
            log.warning("Ignis update check failed: %s", exc)
            errors.append(str(exc))

        github: dict[str, str | None] = {}
        for row in self._github_rows:
            provider = GithubReleaseProvider(row.app, self._bridge, self._state)
            try:
                github[row.app.id] = provider.fetch_latest().tag
            except ProviderError as exc:
                log.warning("update check failed for %s: %s", row.app.id, exc)
                errors.append(str(exc))
                github[row.app.id] = None

        flathub = updatable_refs(self._bridge) if self._flathub_rows else frozenset()

        return CheckResult(
            github=github, flathub=flathub, ignis=ignis_tag, errors=tuple(errors)
        )

    def _apply_check(self, result: CheckResult) -> bool:
        """Show what the refresh found. Runs on the main loop."""
        self._self_row.show_available(result.ignis)

        for row in self._github_rows:
            provider = GithubReleaseProvider(row.app, self._bridge, self._state)
            installed = provider.installed_tag()
            latest = result.github.get(row.app.id)
            if installed is None:
                row.show("Not installed", updatable=False)
            elif latest and latest != installed:
                row.show(f"{installed}  →  {latest}", updatable=True)
            else:
                row.show(f"{installed} — up to date", updatable=False)

        for row in self._flathub_rows:
            ref = row.app.source.ref  # type: ignore[union-attr]
            provider = FlathubProvider(row.app, self._bridge, self._state)
            if provider.status() is not InstallStatus.INSTALLED:
                row.show("Not installed", updatable=False, visible=False)
            elif ref in result.flathub:
                row.show("Update available", updatable=True)
            else:
                row.show("Up to date", updatable=False)

        self._refresh_button.set_sensitive(True)
        self._spinner.set_visible(False)
        if result.errors:
            # Rule 4: a failed check is reported, never silently treated as
            # "everything is up to date".
            self._banner.set_title(result.errors[0])
            self._banner.set_revealed(True)
        self._on_changed()
        return GLib.SOURCE_REMOVE

    def _start_self_update(self) -> None:
        """Install a newer Ignis, then tell the user to restart."""
        run_action(
            self,
            f"Updating {APP_NAME}",
            self._updater.install,
            on_done=self._after_update,
        )

    def _start_app_update(self, row: _AppUpdateRow) -> None:
        """Update one catalog app, using the right provider for its source."""
        if isinstance(row.app.source, GithubSource):
            provider = GithubReleaseProvider(row.app, self._bridge, self._state)
            action = provider.run_install
        else:
            action = FlathubProvider(row.app, self._bridge, self._state).update

        run_action(
            self, f"Updating {row.app.name}", action, on_done=self._after_update
        )

    def _after_update(self) -> None:
        """Re-check everything once an update finishes."""
        self.check_for_updates()
