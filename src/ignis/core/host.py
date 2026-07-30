"""HostBridge — the single chokepoint for running external commands.

Every external command in Ignis goes through this module so that it is
logged, streamed, and works both inside the Flatpak sandbox (via
``flatpak-spawn --host``) and in a plain development checkout.

No other module may import ``subprocess``. See CLAUDE.md hard rule 2.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

#: Prefix used to escape the Flatpak sandbox and run on the host.
HOST_PREFIX: tuple[str, ...] = ("flatpak-spawn", "--host")

#: Marker file present inside every Flatpak sandbox.
FLATPAK_INFO = Path("/.flatpak-info")

#: Exit code reported when the executable could not be found.
EXIT_NOT_FOUND = 127

#: Exit code reported when the command exceeded its timeout.
EXIT_TIMEOUT = 124

LineCallback = Callable[[str], None]


@dataclass(frozen=True)
class CommandResult:
    """Outcome of one command run through the bridge."""

    argv: list[str] = field(default_factory=list)
    returncode: int = 0
    output: str = ""

    @property
    def command(self) -> str:
        """The command as a user could type it, for display and logs."""
        return shlex.join(self.argv)

    @property
    def ok(self) -> bool:
        """True if the command exited successfully."""
        return self.returncode == 0

    def tail(self, lines: int = 12) -> str:
        """Last few output lines, for error messages."""
        return "\n".join(self.output.splitlines()[-lines:])


class CommandError(RuntimeError):
    """Raised when a command exits nonzero (and the caller wanted a check)."""

    def __init__(self, result: CommandResult) -> None:
        self.result = result
        super().__init__(
            f"Command failed with exit code {result.returncode}: {result.command}"
        )


class HostBridge:
    """Runs commands on the host, streaming and logging their output."""

    def __init__(self, *, use_host_spawn: bool | None = None) -> None:
        """``use_host_spawn`` overrides sandbox auto-detection (for tests)."""
        self._use_host_spawn = (
            self.in_flatpak() if use_host_spawn is None else use_host_spawn
        )

    @staticmethod
    def in_flatpak() -> bool:
        """True when running inside a Flatpak sandbox."""
        return FLATPAK_INFO.exists()

    @property
    def uses_host_spawn(self) -> bool:
        """True when commands are wrapped in ``flatpak-spawn --host``."""
        return self._use_host_spawn

    def resolve_argv(self, argv: Sequence[str]) -> list[str]:
        """The argv actually handed to the OS, including any sandbox prefix."""
        if self._use_host_spawn:
            return [*HOST_PREFIX, *argv]
        return list(argv)

    def run(
        self,
        argv: Sequence[str],
        *,
        on_line: LineCallback | None = None,
        timeout: float | None = None,
        check: bool = True,
    ) -> CommandResult:
        """Run ``argv`` on the host and return its result.

        ``on_line`` is invoked for each output line **from a worker thread** —
        UI callers must marshal to the main loop with ``GLib.idle_add``.
        Raises :class:`CommandError` on failure unless ``check=False``.
        """
        argv = list(argv)
        real_argv = self.resolve_argv(argv)
        display = shlex.join(argv)
        log.info("run: %s", display)

        try:
            result = self._execute(argv, real_argv, on_line, timeout)
        except FileNotFoundError as exc:
            message = f"Command not found: {real_argv[0]} ({exc.strerror})"
            result = CommandResult(argv=argv, returncode=EXIT_NOT_FOUND, output=message)
        except OSError as exc:
            message = f"Could not start command: {exc}"
            result = CommandResult(argv=argv, returncode=EXIT_NOT_FOUND, output=message)

        log.info("exit %d: %s", result.returncode, display)
        if result.output:
            log.info("output of %s:\n%s", display, result.output)

        if check and not result.ok:
            raise CommandError(result)
        return result

    def check(self, argv: Sequence[str], *, timeout: float | None = 30) -> bool:
        """True if ``argv`` exits zero. Never raises — for status probes."""
        return self.run(argv, timeout=timeout, check=False).ok

    def _execute(
        self,
        argv: list[str],
        real_argv: list[str],
        on_line: LineCallback | None,
        timeout: float | None,
    ) -> CommandResult:
        """Spawn the process and pump its merged output."""
        proc = subprocess.Popen(  # noqa: S603 - argv list, never shell=True
            real_argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        lines: list[str] = []
        reader = threading.Thread(
            target=self._pump, args=(proc, lines, on_line), daemon=True
        )
        reader.start()

        timed_out = False
        try:
            returncode = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            returncode = proc.wait()

        reader.join(timeout=5)

        if timed_out:
            lines.append(f"[ignis] timed out after {timeout}s and was terminated")
            returncode = EXIT_TIMEOUT

        return CommandResult(
            argv=argv, returncode=returncode, output="\n".join(lines)
        )

    @staticmethod
    def _pump(
        proc: subprocess.Popen[str],
        lines: list[str],
        on_line: LineCallback | None,
    ) -> None:
        """Read merged output line by line until the pipe closes."""
        stream = proc.stdout
        if stream is None:
            return
        try:
            for raw in stream:
                line = raw.rstrip("\n")
                lines.append(line)
                if on_line is None:
                    continue
                try:
                    on_line(line)
                except Exception:
                    # A misbehaving UI callback must not kill the command.
                    log.exception("output callback raised")
        except (ValueError, OSError):
            # Pipe closed underneath us (e.g. after kill on timeout).
            log.debug("output stream closed early", exc_info=True)
        finally:
            try:
                stream.close()
            except OSError:
                log.debug("could not close output stream", exc_info=True)
