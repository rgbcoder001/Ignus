"""Provider contract: status/install/uninstall for one catalog app.

Every provider is a thin, generic wrapper over :class:`HostBridge` — no
provider may import ``subprocess`` directly (CLAUDE.md hard rule 2).
"""

from __future__ import annotations

import base64
import logging
import shlex
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


def substitute(text: str, values: dict[str, str]) -> str:
    """Replace ``{key}`` placeholders with the user's answers.

    Plain replacement rather than str.format: catalog text and unit files
    contain braces of their own, and format() would choke on them.
    """
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def shell_preamble(values: dict[str, str]) -> str:
    """Shell assignments making the user's answers available to a script.

    Values are quoted with shlex, so a stray quote or space in an answer
    cannot break out into the surrounding script.
    """
    if not values:
        return ""
    lines = [f"{key}={shlex.quote(value)}" for key, value in sorted(values.items())]
    return "\n".join(lines) + "\n"


def write_host_file(bridge: HostBridge, path: Path, content: str) -> None:
    """Write a file on the host, creating parent directories.

    The content is base64'd on the way over rather than interpolated into a
    heredoc: it can then contain any characters at all — quotes, backslashes,
    or a line that happens to match the heredoc terminator — without the
    command needing to be escaped correctly.
    """
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    command = (
        f"mkdir -p {shlex.quote(str(path.parent))} && "
        f"printf %s {shlex.quote(encoded)} | base64 -d > {shlex.quote(str(path))}"
    )
    try:
        bridge.run(["bash", "-c", command], timeout=60, check=True)
    except CommandError as exc:
        raise InstallError(f"Could not write {path}: {exc.result.tail(3)}", result=exc.result) from exc


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


def run_bundled_script(
    bridge: HostBridge,
    relative_path: str,
    on_line: LineCallback,
    values: dict[str, str] | None = None,
) -> None:
    """Run a script bundled under ``scripts/`` on the host.

    The script's *content* — not its path — is sent to the host: inside the
    Flatpak sandbox, ``/app/share/ignis/scripts/...`` is a sandbox-only mount
    that ``flatpak-spawn --host`` cannot see, so the file is read here (where
    it's visible) and executed via ``bash -c <content>`` (still an argv list,
    never ``shell=True``).

    Any ``values`` are prepended as quoted shell assignments, so a script can
    use the user's answers as ordinary variables.
    """
    script_path = resolve_script(relative_path)
    try:
        content = script_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InstallError(f"Could not read bundled script {script_path}: {exc}") from None

    if values:
        content = _insert_after_shebang(content, shell_preamble(values))

    try:
        bridge.run(["bash", "-c", content], on_line=on_line, timeout=None, check=True)
    except CommandError as exc:
        raise InstallError(
            f"Script {relative_path} failed with exit code {exc.result.returncode}",
            result=exc.result,
        ) from exc


def _insert_after_shebang(content: str, preamble: str) -> str:
    """Insert ``preamble`` below the shebang, which must stay on line one."""
    if not content.startswith("#!"):
        return preamble + content
    shebang, _, rest = content.partition("\n")
    return f"{shebang}\n{preamble}{rest}"


def check_status(
    bridge: HostBridge,
    check_cmd: tuple[str, ...] | None,
    values: dict[str, str] | None = None,
) -> InstallStatus:
    """Shared status logic for providers whose only signal is a check_cmd.

    ``values`` are substituted into the command, so a check can refer to an
    answer the user gave — a NAS mount cannot be looked for until it is known
    where the user asked to mount it. With no answers saved, the placeholder
    is left as-is, the command fails, and the app reads as not installed —
    which is exactly right for something not yet set up.
    """
    if check_cmd is None:
        return InstallStatus.UNKNOWN
    resolved = [substitute(part, values or {}) for part in check_cmd]
    return (
        InstallStatus.INSTALLED
        if bridge.check(resolved, timeout=15)
        else InstallStatus.NOT_INSTALLED
    )
