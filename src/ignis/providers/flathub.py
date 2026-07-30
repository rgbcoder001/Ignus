"""Installs Flatpaks from Flathub."""

from __future__ import annotations

import shlex

from ignis.core.host import CommandError
from ignis.providers.base import InstallError, InstallStatus, LineCallback, Provider


class FlathubProvider(Provider):
    """Installs, uninstalls and checks the status of a Flathub app."""

    supports_uninstall = True

    @property
    def ref(self) -> str:
        """The Flathub application id (e.g. ``com.obsproject.Studio``)."""
        return self.app.source.ref  # type: ignore[attr-defined]

    def status(self) -> InstallStatus:
        """INSTALLED if `flatpak info <ref>` succeeds, else NOT_INSTALLED."""
        installed = self.bridge.check(["flatpak", "info", self.ref], timeout=15)
        return InstallStatus.INSTALLED if installed else InstallStatus.NOT_INSTALLED

    def install(self, on_line: LineCallback) -> None:
        """Run `flatpak install -y --noninteractive flathub <ref>`."""
        try:
            self.bridge.run(
                ["flatpak", "install", "-y", "--noninteractive", "flathub", self.ref],
                on_line=on_line,
                timeout=None,
                check=True,
            )
        except CommandError as exc:
            raise InstallError(
                f"Installing {self.app.name} failed with exit code {exc.result.returncode}",
                result=exc.result,
            ) from exc

    def uninstall(self, on_line: LineCallback) -> None:
        """Run `flatpak uninstall -y <ref>`."""
        try:
            self.bridge.run(
                ["flatpak", "uninstall", "-y", self.ref],
                on_line=on_line,
                timeout=None,
                check=True,
            )
        except CommandError as exc:
            raise InstallError(
                f"Uninstalling {self.app.name} failed with exit code {exc.result.returncode}",
                result=exc.result,
            ) from exc

    def describe_source(self) -> str:
        """e.g. 'Installs from Flathub: com.obsproject.Studio'."""
        return f"Installs from Flathub: {self.ref}"

    def command_preview(self) -> str:
        """The exact install command, for the detail view's transparency row."""
        return shlex.join(["flatpak", "install", "-y", "--noninteractive", "flathub", self.ref])
