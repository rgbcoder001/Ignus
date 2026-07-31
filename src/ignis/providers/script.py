"""Runs a vetted shell script bundled with Ignis."""

from __future__ import annotations

from ignis.providers.base import (
    InstallStatus,
    LineCallback,
    Provider,
    check_status,
    run_bundled_script,
)


class ScriptProvider(Provider):
    """Runs a bundled setup script. Scripts can't be cleanly uninstalled."""

    supports_uninstall = False

    @property
    def _source(self):
        return self.app.source

    def status(self) -> InstallStatus:
        """INSTALLED/NOT_INSTALLED via check_cmd if the catalog set one, else UNKNOWN."""
        return check_status(
            self.bridge, self._source.check_cmd, self.state.app_settings(self.app.id)
        )

    def install(self, on_line: LineCallback) -> None:
        """Run the bundled script with the user's answers as shell variables."""
        run_bundled_script(
            self.bridge,
            self._source.file,
            on_line,
            values=self.state.app_settings(self.app.id),
        )

    def describe_source(self) -> str:
        """e.g. 'Runs a bundled setup script'."""
        return f"Runs a bundled setup script ({self._source.file})"

    def command_preview(self) -> str:
        """A representative command; the real invocation streams the file's
        content over `bash -c` rather than referencing this path directly —
        see run_bundled_script() for why."""
        return f"bash {self._source.file}"
