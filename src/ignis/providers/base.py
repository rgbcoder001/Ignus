"""Provider contract: status/install/uninstall for one catalog app.

Every provider is a thin, generic wrapper over :class:`HostBridge` — no
provider may import ``subprocess`` directly (CLAUDE.md hard rule 2).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from enum import Enum, auto

from pathlib import Path, PurePosixPath

from ignis.core import paths
from ignis.core.catalog import App
from ignis.core.host import CommandError, CommandResult, HostBridge
from ignis.core.state import State

log = logging.getLogger(__name__)

LineCallback = Callable[[str], None]


class InstallStatus(Enum):
    """Whether — and how — an app is currently installed."""

    NOT_INSTALLED = auto()
    INSTALLED = auto()
    UPDATE_AVAILABLE = auto()
    UNKNOWN = auto()


class ProviderError(Exception):
    """Base class for provider failures."""


class InstallError(ProviderError):
    """Install, uninstall or post-install action failed.

    Carries the underlying :class:`CommandResult` (when there is one) so the
    UI can show the exact failing command and its output — never a bare
    "something went wrong" (CLAUDE.md hard rule 4).
    """

    def __init__(self, message: str, result: CommandResult | None = None) -> None:
        super().__init__(message)
        self.result = result


class NotSupportedError(ProviderError):
    """This provider does not support the requested action (e.g. uninstall)."""


class UnsupportedSourceError(ProviderError):
    """No provider exists yet for this catalog entry's source type."""


class Provider(ABC):
    """Installs, uninstalls and reports the status of one catalog app."""

    #: Whether this provider can remove an installed app. Ujust recipes and
    #: bundled scripts generally can't be cleanly reversed.
    supports_uninstall: bool = True

    def __init__(self, app: App, bridge: HostBridge, state: State) -> None:
        self.app = app
        self.bridge = bridge
        self.state = state

    @abstractmethod
    def status(self) -> InstallStatus:
        """Current install status. Must be fast — no network unless cached."""

    @abstractmethod
    def install(self, on_line: LineCallback) -> None:
        """Install the app. Raises :class:`InstallError` on failure."""

    def uninstall(self, on_line: LineCallback) -> None:
        """Remove the app. Raises :class:`NotSupportedError` by default."""
        raise NotSupportedError(f"{self.app.name} can't be uninstalled from Ignis")

    def launch_command(self) -> list[str] | None:
        """argv that starts the installed app, or None if Ignis can't.

        Providers that install something runnable override this. A ujust
        recipe or a config script generally has nothing to launch.
        """
        return None

    def shortcut_entry(self) -> str | None:
        """.desktop contents for a desktop shortcut, or None if unsupported."""
        return None

    def launch(self) -> None:
        """Start the installed app without waiting for it to exit."""
        argv = self.launch_command()
        if argv is None:
            raise NotSupportedError(f"Ignis can't open {self.app.name}")
        try:
            self.bridge.spawn(argv)
        except CommandError as exc:
            raise InstallError(
                f"Could not open {self.app.name}", result=exc.result
            ) from exc

    @abstractmethod
    def describe_source(self) -> str:
        """One line describing where this app comes from, for the detail view."""

    @abstractmethod
    def command_preview(self) -> str:
        """The literal command a user could type — shown for transparency."""

    def run_install(self, on_line: LineCallback) -> None:
        """Install, then run the catalog's ``post_install`` script if set.

        This is the entry point callers use instead of :meth:`install`
        directly, so every source type gets post-install handling for free.
        """
        self.install(on_line)
        if self.app.post_install:
            on_line(f"[ignis] running post-install script: {self.app.post_install}")
            run_bundled_script(self.bridge, self.app.post_install, on_line)


def resolve_script(relative_path: str) -> Path:
    """Resolve a catalog script reference to a real path.

    The catalog writes these either bare (``foo.sh``) or with the repo-relative
    prefix SPEC.md §4.2 uses (``scripts/foo.sh``). scripts_dir() already points
    *at* the scripts folder, so the prefix has to be dropped or the path would
    resolve to ``scripts/scripts/foo.sh``.
    """
    parts = PurePosixPath(relative_path).parts
    if parts and parts[0] == "scripts":
        parts = parts[1:]
    return paths.scripts_dir().joinpath(*parts)


def run_bundled_script(bridge: HostBridge, relative_path: str, on_line: LineCallback) -> None:
    """Run a script bundled under ``scripts/`` on the host.

    The script's *content* — not its path — is sent to the host: inside the
    Flatpak sandbox, ``/app/share/ignis/scripts/...`` is a sandbox-only mount
    that ``flatpak-spawn --host`` cannot see, so the file is read here (where
    it's visible) and executed via ``bash -c <content>`` (still an argv list,
    never ``shell=True``).
    """
    script_path = resolve_script(relative_path)
    try:
        content = script_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InstallError(f"Could not read bundled script {script_path}: {exc}") from None

    try:
        bridge.run(["bash", "-c", content], on_line=on_line, timeout=None, check=True)
    except CommandError as exc:
        raise InstallError(
            f"Script {relative_path} failed with exit code {exc.result.returncode}",
            result=exc.result,
        ) from exc


def check_status(
    bridge: HostBridge, check_cmd: tuple[str, ...] | None
) -> InstallStatus:
    """Shared status logic for providers whose only signal is a check_cmd."""
    if check_cmd is None:
        return InstallStatus.UNKNOWN
    return InstallStatus.INSTALLED if bridge.check(check_cmd, timeout=15) else InstallStatus.NOT_INSTALLED
