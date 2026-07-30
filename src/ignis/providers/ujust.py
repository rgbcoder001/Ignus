"""Runs one of Bazzite's built-in ujust recipes."""

from __future__ import annotations

import shlex

from ignis.core.catalog import UjustSource
from ignis.providers.base import (
    InstallError,
    InstallStatus,
    LineCallback,
    NotSupportedError,
    Provider,
    check_status,
)

#: Markers that a recipe tried to open its interactive menu. Recipes print
#: these and can still exit 0 (setup-sunshine does), so the exit code alone
#: would report a silent success for an install that never happened.
TTY_MARKERS = (
    "could not open a new tty",
    "unable to pick selection",
    "/dev/tty: no such device",
)


def needs_terminal(output: str) -> bool:
    """True if a recipe's output shows it wanted an interactive terminal."""
    lowered = output.lower()
    return any(marker in lowered for marker in TTY_MARKERS)


class UjustProvider(Provider):
    """Runs a ujust recipe with an explicit, non-interactive action."""

    @property
    def source(self) -> UjustSource:
        """This app's ujust source definition."""
        return self.app.source  # type: ignore[return-value]

    @property
    def supports_uninstall(self) -> bool:
        """Only when the catalog says which action reverses the install."""
        return self.source.uninstall_args is not None

    def status(self) -> InstallStatus:
        """INSTALLED/NOT_INSTALLED via check_cmd if the catalog set one, else UNKNOWN."""
        return check_status(self.bridge, self.source.check_cmd)

    def install(self, on_line: LineCallback) -> None:
        """Run the recipe's install action."""
        self._run(self.source.args, on_line)

    def uninstall(self, on_line: LineCallback) -> None:
        """Run the recipe's uninstall action, if the catalog defines one."""
        args = self.source.uninstall_args
        if args is None:
            raise NotSupportedError(f"{self.app.name} can't be uninstalled from Ignis")
        self._run(args, on_line)

    def _run(self, args: tuple[str, ...], on_line: LineCallback) -> None:
        """Run `ujust <recipe> <args>`, treating a menu prompt as a failure."""
        argv = ["ujust", self.source.recipe, *args]
        result = self.bridge.run(argv, on_line=on_line, timeout=None, check=False)

        if needs_terminal(result.output):
            raise InstallError(
                f"`{shlex.join(argv)}` tried to open an interactive menu, which "
                "Ignis can't answer. This catalog entry needs a non-interactive "
                'action (for example args = ["install"]).',
                result=result,
            )
        if not result.ok:
            raise InstallError(
                f"{shlex.join(argv)} failed with exit code {result.returncode}",
                result=result,
            )

    def describe_source(self) -> str:
        """e.g. \"Runs Bazzite's built-in setup-sunshine recipe\"."""
        return f"Runs Bazzite's built-in `{self.source.recipe}` recipe"

    def command_preview(self) -> str:
        """The exact recipe invocation, for the detail view's transparency row."""
        return shlex.join(["ujust", self.source.recipe, *self.source.args])
