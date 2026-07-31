"""Runs a service as a rootless Podman container, managed by systemd.

Uses Quadlet, which Bazzite documents as its own way to run services and
which Podman recommends over ``podman generate systemd``. Ignis writes a
``.container`` unit; systemd and Podman do the rest.
"""

from __future__ import annotations

import logging
import re
import shlex
from pathlib import Path

from ignis.core.catalog import ContainerSource
from ignis.core.host import CommandError
from ignis.providers.base import (
    InstallError,
    InstallStatus,
    LineCallback,
    Provider,
    substitute,
    write_host_file,
)

log = logging.getLogger(__name__)

UNIT_PREFIX = "ignis-"

#: A setting placeholder that survived substitution — a catalog bug.
PLACEHOLDER = re.compile(r"\{[a-z][a-z0-9_]*\}")


def unresolved_placeholders(source: ContainerSource, values: dict[str, str]) -> list[str]:
    """Placeholders in the source that the user's answers don't cover.

    Normally impossible — the setup dialog runs whenever an app declares
    settings — but a catalog typo (placeholder key not matching a setting
    key) would otherwise produce a literal ``{books_dir}`` directory on disk
    and a service pointed at nothing.
    """
    leftover: set[str] = set()
    for item in (*source.volumes, *source.environment):
        leftover.update(PLACEHOLDER.findall(substitute(item, values)))
    return sorted(leftover)


def quadlet_dir() -> Path:
    """Where rootless Quadlet units live.

    Deliberately not XDG_CONFIG_HOME: inside the sandbox that points at the
    app's private ~/.var/app/<id>/config, where Podman would never look. Same
    trap as core/paths.py:desktop_entries_dir().
    """
    return Path.home() / ".config" / "containers" / "systemd"


def data_dir(app_id: str) -> Path:
    """Where a service keeps its own database and configuration."""
    return Path.home() / ".local" / "share" / "ignis" / app_id


def build_unit(
    name: str,
    source: ContainerSource,
    values: dict[str, str],
    config_dir: Path,
) -> str:
    """Assemble a Quadlet .container unit.

    Pure so it can be tested without a container runtime.
    """
    lines = [
        "[Unit]",
        f"Description={name} (managed by Ignis)",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Container]",
        f"Image={source.image}",
        f"PublishPort={source.port}:{source.port}",
        f"Volume={config_dir}:/config:Z",
    ]
    for volume in source.volumes:
        lines.append(f"Volume={substitute(volume, values)}")
    for variable in source.environment:
        lines.append(f"Environment={substitute(variable, values)}")

    lines += [
        "",
        "[Service]",
        "Restart=on-failure",
        "",
        "[Install]",
        "WantedBy=default.target",
        "",
    ]
    return "\n".join(lines)


class ContainerProvider(Provider):
    """Installs, starts and removes a containerised service."""

    supports_uninstall = True

    @property
    def source(self) -> ContainerSource:
        """This app's container definition."""
        return self.app.source  # type: ignore[return-value]

    @property
    def unit_name(self) -> str:
        """The systemd service this becomes once Quadlet has generated it."""
        return f"{UNIT_PREFIX}{self.app.id}"

    @property
    def unit_path(self) -> Path:
        """Where the Quadlet unit is written."""
        return quadlet_dir() / f"{self.unit_name}.container"

    def status(self) -> InstallStatus:
        """Whether the service is running. Local and fast — no network."""
        active = self.bridge.check(
            ["systemctl", "--user", "is-active", f"{self.unit_name}.service"],
            timeout=15,
        )
        return InstallStatus.INSTALLED if active else InstallStatus.NOT_INSTALLED

    def install(self, on_line: LineCallback) -> None:
        """Write the unit, reload systemd and start the service."""
        values = self.state.app_settings(self.app.id)
        config_dir = data_dir(self.app.id)

        missing = unresolved_placeholders(self.source, values)
        if missing:
            raise InstallError(
                f"{self.app.name} is missing details it needs: "
                f"{', '.join(missing)}. Open its page and install again to be "
                "asked for them."
            )

        on_line(f"[ignis] writing service definition to {self.unit_path}")
        write_host_file(
            self.bridge,
            self.unit_path,
            build_unit(self.app.name, self.source, values, config_dir),
        )

        # The container writes here as its own user; create it first so Podman
        # does not make it root-owned. Same for any writable volume under the
        # user's home (e.g. a cache dir declared with the %h specifier).
        self._run(["mkdir", "-p", str(config_dir)], on_line)
        for host_dir in self._home_volume_dirs(values):
            self._run(["mkdir", "-p", host_dir], on_line)

        on_line("[ignis] asking systemd to pick up the new service")
        self._run(["systemctl", "--user", "daemon-reload"], on_line)

        on_line(f"[ignis] pulling {self.source.image} — this can take a while")
        self._run(
            ["systemctl", "--user", "start", f"{self.unit_name}.service"],
            on_line,
            timeout=None,
        )

        self._enable_lingering(on_line)
        on_line(f"[ignis] {self.app.name} is running at http://localhost:{self.source.port}")

    def uninstall(self, on_line: LineCallback) -> None:
        """Stop the service and delete its unit — never its data."""
        self.bridge.run(
            ["systemctl", "--user", "stop", f"{self.unit_name}.service"],
            on_line=on_line,
            timeout=120,
            check=False,
        )
        self._run(["rm", "-f", str(self.unit_path)], on_line)
        self._run(["systemctl", "--user", "daemon-reload"], on_line)

        # Deliberately left in place: the config volume holds the user's
        # library database, and the media folder is not ours at all.
        on_line(f"[ignis] your data in {data_dir(self.app.id)} has been left alone")

    def launch_command(self) -> list[str] | None:
        """Opening a server means opening its web interface."""
        return ["xdg-open", f"http://localhost:{self.source.port}"]

    def describe_source(self) -> str:
        """e.g. 'Runs as a background service from docker.io/gotson/komga'."""
        return f"Runs as a background service from {self.source.image}"

    def command_preview(self) -> str:
        """What the install actually does, for the transparency row."""
        return (
            f"Writes {self.unit_path}\n"
            f"then: systemctl --user start {self.unit_name}.service\n"
            f"Reachable at http://localhost:{self.source.port}"
        )

    def _home_volume_dirs(self, values: dict[str, str]) -> list[str]:
        """Host paths of writable volumes that live under the user's home.

        Only home paths: a media folder on /mnt is the NAS's and must already
        exist — creating it here would just mask a missing mount.
        """
        home = Path.home()
        dirs: list[str] = []
        for volume in self.source.volumes:
            host = substitute(volume, values).split(":", 1)[0]
            if host.startswith("%h/"):
                host = str(home / host[3:])
            if host.startswith(str(home)):
                dirs.append(host)
        return dirs

    def _enable_lingering(self, on_line: LineCallback) -> None:
        """Let the service run without the user being logged in.

        Optional: without it the service still works, it just stops when the
        session ends. Not worth failing an otherwise good install over.
        """
        user = self.bridge.run(["id", "-un"], timeout=15, check=False)
        if not user.ok or not user.output.strip():
            return
        username = user.output.strip().splitlines()[0]

        # Already on? Then don't ask for a password again on every reinstall.
        linger = self.bridge.run(
            ["loginctl", "show-user", username, "--property=Linger"],
            timeout=15,
            check=False,
        )
        if linger.ok and "Linger=yes" in linger.output:
            return

        result = self.bridge.run(
            ["pkexec", "loginctl", "enable-linger", username],
            on_line=on_line,
            timeout=120,
            check=False,
        )
        if not result.ok:
            on_line(
                "[ignis] could not enable start-at-boot; the service will run "
                "while you are logged in"
            )

    def _run(self, argv: list[str], on_line: LineCallback, timeout: float | None = 120) -> None:
        """Run a step, turning a failure into a readable InstallError."""
        try:
            self.bridge.run(argv, on_line=on_line, timeout=timeout, check=True)
        except CommandError as exc:
            raise InstallError(
                f"{shlex.join(argv)} failed with exit code {exc.result.returncode}",
                result=exc.result,
            ) from exc
