"""Runs one of Bazzite's built-in ujust recipes."""

from __future__ import annotations

import shlex

from ignis.core.host import CommandError
from ignis.providers.base import (
    InstallError,
    InstallStatus,
    LineCallback,
    Provider,
    check_status,
)


class UjustProvider(Provider):
    """Runs a ujust recipe. Recipes can't be cleanly uninstalled from Ignis."""

    supports_uninstall = False

    @property
    def _source(self):
        return self.app.source

    def status(self) -> InstallStatus:
        """INSTALLED/NOT_INSTALLED via check_cmd if the catalog set one, else UNKNOWN."""
        return check_status(self.bridge, self._source.check_cmd)

    def install(self, on_line: LineCallback) -> None:
        """Run `ujust <recipe>`."""
        try:
            self.bridge.run(
                ["ujust", self._source.recipe], on_line=on_line, timeout=None, check=True
            )
        except CommandError as exc:
            raise InstallError(
                f"ujust {self._source.recipe} failed with exit code {exc.result.returncode}",
                result=exc.result,
            ) from exc

    def describe_source(self) -> str:
        """e.g. \"Runs Bazzite's built-in setup-sunshine recipe\"."""
        return f"Runs Bazzite's built-in `{self._source.recipe}` recipe"

    def command_preview(self) -> str:
        """The exact recipe invocation, for the detail view's transparency row."""
        return shlex.join(["ujust", self._source.recipe])
