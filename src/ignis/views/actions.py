"""Runs a provider action behind a ProgressDialog, off the main loop.

Shared by the Detail and Updates views so install/update/uninstall all get
identical progress and failure handling.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import GLib, Gtk  # noqa: E402

from ignis.providers.base import LineCallback, ProviderError
from ignis.views.progress import ProgressDialog

log = logging.getLogger(__name__)

Action = Callable[[LineCallback], None]


def run_action(
    parent: Gtk.Widget,
    title: str,
    action: Action,
    on_done: Callable[[], None] | None = None,
) -> None:
    """Run ``action`` in a worker thread, streaming output into a dialog.

    ``on_done`` runs on the main loop after either outcome, so callers can
    refresh their status display.
    """
    dialog = ProgressDialog(title)
    dialog.present(parent)

    def on_line(line: str) -> None:
        GLib.idle_add(dialog.append_line, line)

    def finish(error: ProviderError | None) -> bool:
        if error is None:
            dialog.finish_success()
        else:
            dialog.finish_failure(getattr(error, "result", None), str(error))
            log.error("%s failed: %s", title, error)
        if on_done is not None:
            on_done()
        return GLib.SOURCE_REMOVE

    def worker() -> None:
        try:
            action(on_line)
        except ProviderError as exc:
            GLib.idle_add(finish, exc)
        except Exception as exc:  # noqa: BLE001 - see comment
            # Anything unexpected (an OSError mid-download, a bug) must still
            # reach the dialog: otherwise it stays non-closable forever and the
            # user is stuck with no way out and no explanation.
            log.exception("unexpected failure during %s", title)
            GLib.idle_add(finish, ProviderError(f"Unexpected error: {exc}"))
        else:
            GLib.idle_add(finish, None)

    threading.Thread(target=worker, daemon=True).start()
