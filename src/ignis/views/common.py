"""Small widgets and helpers shared across views."""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gio, GLib, Gtk  # noqa: E402

from ignis.core import hardware, paths
from ignis.core.catalog import App

log = logging.getLogger(__name__)


def open_log_folder(widget: Gtk.Widget) -> None:
    """Open the folder holding ignis.log in the file manager.

    ``widget`` is any widget in the window: Gtk.FileLauncher's parent is
    typed GtkWindow*, so the window has to be looked up rather than passed
    a dialog or a page.
    """
    launcher = Gtk.FileLauncher(file=Gio.File.new_for_path(str(paths.log_file())))
    root = widget.get_root()
    parent = root if isinstance(root, Gtk.Window) else None
    launcher.open_containing_folder(parent, None, _finish_open_log_folder)


def _finish_open_log_folder(launcher: Gtk.FileLauncher, result: Gio.AsyncResult) -> None:
    """Report (but never crash on) a failure to open the log folder."""
    try:
        launcher.open_containing_folder_finish(result)
    except GLib.Error:
        log.warning("could not open the log folder", exc_info=True)


def app_icon(app: App, size: int) -> Gtk.Image:
    """The catalog icon for ``app``, falling back to a generic symbol."""
    if app.icon:
        icon_path = paths.icons_dir() / app.icon
        try:
            if icon_path.is_file():
                image = Gtk.Image.new_from_file(str(icon_path))
                image.set_pixel_size(size)
                return image
            log.info("catalog icon missing for %s: %s", app.id, icon_path)
        except OSError:
            log.warning("could not load icon for %s", app.id, exc_info=True)
    return Gtk.Image(icon_name="application-x-executable-symbolic", pixel_size=size)


def hardware_badges(app: App, vendors: frozenset[str]) -> list[Gtk.Label]:
    """Vendor badges for an app, styled and explained by detection state."""
    badges = []
    for vendor in sorted(app.hardware):
        state = hardware.badge_state(vendor, vendors)
        badge = Gtk.Label(
            label=hardware.label(vendor),
            css_classes=["caption", hardware.BADGE_STYLES[state]],
            valign=Gtk.Align.CENTER,
            tooltip_text=hardware.badge_tooltip(vendor, state),
        )
        badges.append(badge)
    return badges


def badge(text: str, style: str = "dim-label", tooltip: str | None = None) -> Gtk.Label:
    """A small caption label used as a row suffix."""
    return Gtk.Label(
        label=text,
        css_classes=["caption", style],
        valign=Gtk.Align.CENTER,
        tooltip_text=tooltip,
    )
