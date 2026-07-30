"""A duck-typed HostBridge double for provider unit tests.

Providers only call ``bridge.run()`` and ``bridge.check()`` — this fake
implements that same interface without spawning real processes, so provider
tests are fast, portable (no real `flatpak`/`ujust`/`bash` required) and
never touch the network.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ignis.core.host import CommandError, CommandResult


@dataclass
class RecordedCall:
    """One call made against the fake bridge."""

    argv: list[str]
    on_line: Callable[[str], None] | None
    timeout: float | None
    check: bool


class FakeBridge:
    """Returns canned :class:`CommandResult`s keyed by argv tuple."""

    def __init__(self) -> None:
        self.calls: list[RecordedCall] = []
        self._responses: dict[tuple[str, ...], CommandResult] = {}
        self.default_returncode = 0

    def set_result(self, argv: list[str], *, returncode: int = 0, output: str = "") -> None:
        """Program the result for an exact argv."""
        self._responses[tuple(argv)] = CommandResult(
            argv=list(argv), returncode=returncode, output=output
        )

    def run(
        self,
        argv: list[str],
        *,
        on_line: Callable[[str], None] | None = None,
        timeout: float | None = None,
        check: bool = True,
    ) -> CommandResult:
        self.calls.append(RecordedCall(list(argv), on_line, timeout, check))
        result = self._responses.get(
            tuple(argv), CommandResult(argv=list(argv), returncode=self.default_returncode)
        )
        if on_line is not None:
            for line in result.output.splitlines():
                on_line(line)
        if check and not result.ok:
            raise CommandError(result)
        return result

    def check(self, argv: list[str], *, timeout: float | None = 30) -> bool:
        return self.run(argv, timeout=timeout, check=False).ok
