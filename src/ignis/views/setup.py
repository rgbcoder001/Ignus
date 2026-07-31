"""Asks an app's setup questions before it is installed.

Only entries that declare ``[[apps.settings]]`` use this — everything else
installs with no questions at all.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ignis.core.catalog import App, SettingType

log = logging.getLogger(__name__)


class SetupDialog(Adw.Dialog):
    """Collects the answers an app needs, then hands them back."""

    def __init__(
        self,
        app: App,
        current: dict[str, str],
        on_confirm: Callable[[dict[str, str]], None],
    ) -> None:
        super().__init__(title=f"Set up {app.name}", content_width=520)
        self._app = app
        self._on_confirm = on_confirm
        self._rows: dict[str, Adw.EntryRow] = {}

        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="Before installing",
            description="Ignis needs a couple of details to set this up.",
        )
        for setting in app.settings:
            row = Adw.EntryRow(title=setting.label)
            row.set_text(current.get(setting.key, setting.default))
            if setting.help:
                row.set_tooltip_text(setting.help)
            self._rows[setting.key] = row
            group.add(row)

            if setting.help:
                group.add(
                    Adw.ActionRow(
                        subtitle=setting.help,
                        css_classes=["dim-label"],
                        activatable=False,
                    )
                )
        page.add(group)

        header = Adw.HeaderBar(show_end_title_buttons=False)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda _b: self.close())
        header.pack_start(cancel)

        self._continue = Gtk.Button(label="Continue", css_classes=["suggested-action"])
        self._continue.connect("clicked", self._on_continue)
        header.pack_end(self._continue)

        self._banner = Adw.Banner(revealed=False)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.add_top_bar(self._banner)
        toolbar.set_content(page)
        self.set_child(toolbar)

    def _on_continue(self, _button: Gtk.Button) -> None:
        """Validate, then hand the answers back and close."""
        values = {key: row.get_text().strip() for key, row in self._rows.items()}

        missing = [
            setting.label
            for setting in self._app.settings
            if not values.get(setting.key)
        ]
        if missing:
            self._banner.set_title(f"Still needed: {', '.join(missing)}")
            self._banner.set_revealed(True)
            return

        bad_path = next(
            (
                setting.label
                for setting in self._app.settings
                if setting.type is SettingType.PATH
                and not values[setting.key].startswith("/")
            ),
            None,
        )
        if bad_path is not None:
            self._banner.set_title(f"{bad_path} must start with a slash")
            self._banner.set_revealed(True)
            return

        self.close()
        self._on_confirm(values)
