"""Installs Flatpaks from Flathub."""

from __future__ import annotations

import shlex

from ignis.core.host import CommandError, HostBridge
from ignis.providers.base import InstallError, InstallStatus, LineCallback, Provider

FLATHUB_REMOTE = "flathub"

#: Installation scopes. --user is preferred because it needs no administrator
#: password, which an unattended install cannot supply.
USER_SCOPE = "--user"
SYSTEM_SCOPE = "--system"


def remote_scope(bridge: HostBridge) -> str:
    """Which installation to install from, as an explicit flatpak flag.

    Bazzite configures the flathub remote in *both* the user and system
    installations, and an unqualified `flatpak install flathub <ref>` then
    fails outright: "Remote 'flathub' found in multiple installations,
    unable to proceed in non-interactive mode". The scope has to be stated.
    """
    for scope in (USER_SCOPE, SYSTEM_SCOPE):
        result = bridge.run(
            ["flatpak", "remotes", scope, "--columns=name"], timeout=30, check=False
        )
        if result.ok and FLATHUB_REMOTE in result.output.split():
            return scope
    raise InstallError(
        "The flathub app store isn't set up on this system, so Ignis has "
        "nowhere to install from. Add it with: flatpak remote-add "
        "--if-not-exists --user flathub "
        "https://dl.flathub.org/repo/flathub.flatpakrepo"
    )


def installed_scope(bridge: HostBridge, ref: str) -> str | None:
    """Which installation ``ref`` is installed in, or None if it isn't."""
    for scope in (USER_SCOPE, SYSTEM_SCOPE):
        if bridge.check(["flatpak", "info", scope, ref], timeout=15):
            return scope
    return None


class FlathubProvider(Provider):
    """Installs, uninstalls and checks the status of a Flathub app."""

    supports_uninstall = True

    @property
    def ref(self) -> str:
        """The Flathub application id (e.g. ``com.obsproject.Studio``)."""
        return self.app.source.ref  # type: ignore[attr-defined]

    def status(self) -> InstallStatus:
        """INSTALLED if `flatpak info <ref>` succeeds, else NOT_INSTALLED.

        Unqualified on purpose: this should report an app as installed
        whether it came from a user install or shipped with the system.
        """
        installed = self.bridge.check(["flatpak", "info", self.ref], timeout=15)
        return InstallStatus.INSTALLED if installed else InstallStatus.NOT_INSTALLED

    def install(self, on_line: LineCallback) -> None:
        """Install from Flathub, into whichever installation has the remote."""
        scope = remote_scope(self.bridge)
        try:
            self.bridge.run(
                [
                    "flatpak", "install", "-y", "--noninteractive",
                    scope, FLATHUB_REMOTE, self.ref,
                ],
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
        """Remove the app from whichever installation it actually lives in."""
        scope = installed_scope(self.bridge, self.ref)
        if scope is None:
            raise InstallError(f"{self.app.name} doesn't appear to be installed.")
        try:
            self.bridge.run(
                ["flatpak", "uninstall", "-y", "--noninteractive", scope, self.ref],
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
        """The install command. Shows the usual --user scope; the real scope
        is resolved at install time and can't be probed from the main loop."""
        return shlex.join(
            [
                "flatpak", "install", "-y", "--noninteractive",
                USER_SCOPE, FLATHUB_REMOTE, self.ref,
            ]
        )
