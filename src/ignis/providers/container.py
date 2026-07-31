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


def data_root() -> Path:
    """The one folder Ignis keeps container data under."""
    return Path.home() / ".local" / "share" / "ignis"


def data_dir(app_id: str) -> Path:
    """Where a service keeps its own database and configuration."""
    return data_root() / app_id


def is_ignis_data_dir(path: Path) -> bool:
    """True only for a per-app folder directly inside Ignis's data root.

    The guard on the one genuinely destructive operation here: deleting a
    user's library database is bad, deleting anything else would be
    unforgivable.
    """
    try:
        relative = path.resolve().relative_to(data_root().resolve())
    except (ValueError, OSError):
        return False
    return len(relative.parts) == 1


def _verify_script(container: str, host_path: str, inside: str) -> str:
    """Shell that compares what the host sees with what the container sees.

    Comparing the two is what makes the result actionable: files on the host
    but none in the container means the bind mount missed the share, whereas
    nothing on either side means the folder really is empty.
    """
    name = shlex.quote(container)
    host = shlex.quote(host_path)
    target = shlex.quote(inside)
    return f"""
host_count=$(ls -A {host} 2>/dev/null | wc -l)
echo "[ignis] {host_path} holds $host_count item(s) on this computer"

for _ in $(seq 1 10); do
    if podman exec {name} test -d {target} 2>/dev/null; then
        seen=$(podman exec {name} sh -c 'ls -A {inside} 2>/dev/null | wc -l' 2>/dev/null)
        echo "[ignis] {inside} holds ${{seen:-0}} item(s) inside {container}"
        if [ "${{seen:-0}}" -eq 0 ] && [ "$host_count" -gt 0 ]; then
            echo "[ignis] WARNING: your files are not visible inside the app."
            echo "[ignis] The share was probably not connected when the app"
            echo "[ignis] started. Try installing it again now that {host_path}"
            echo "[ignis] is awake."
        elif [ "$host_count" -eq 0 ]; then
            echo "[ignis] WARNING: {host_path} looks empty on this computer too."
            echo "[ignis] Check the NAS is connected before setting up a library."
        else
            echo "[ignis] Good - point the app at {inside} when it asks."
        fi
        exit 0
    fi
    sleep 2
done
echo "[ignis] Could not look inside {container} to check; it may still be starting."
"""


def is_external_path(host_path: str) -> bool:
    """True for a host path that may be a network mount rather than our own.

    Anything under the user's home is a folder Ignis created; anything else
    is the user's storage — typically the NAS — and needs the automount
    handling below.
    """
    return host_path.startswith("/") and not host_path.startswith(str(Path.home()))


def with_propagation(volume: str) -> str:
    """Add rslave propagation to a bind mount.

    Without this, a container that starts while an automounted share is idle
    binds the empty autofs directory and can *never* see the files: Podman's
    default rprivate propagation means the host mounting it later is
    invisible inside the container, and the container touching the path
    cannot trigger the host's automounter either.
    """
    parts = volume.split(":")
    if len(parts) >= 3 and parts[2]:
        if "slave" in parts[2] or "shared" in parts[2]:
            return volume
        return f"{parts[0]}:{parts[1]}:{parts[2]},rslave"
    return f"{parts[0]}:{parts[1]}:rslave"


def build_unit(
    name: str,
    source: ContainerSource,
    values: dict[str, str],
    config_dir: Path,
    container_name: str = "",
) -> str:
    """Assemble a Quadlet .container unit.

    Pure so it can be tested without a container runtime. ``values`` should
    already be canonical host paths — see ContainerProvider._resolve_paths.
    """
    volumes: list[str] = []
    required_mounts: list[str] = []

    for volume in source.volumes:
        resolved = substitute(volume, values)
        host_path = resolved.split(":", 1)[0]
        if is_external_path(host_path):
            resolved = with_propagation(resolved)
            if host_path not in required_mounts:
                required_mounts.append(host_path)
        volumes.append(resolved)

    lines = [
        "[Unit]",
        f"Description={name} (managed by Ignis)",
        "After=network-online.target",
        "Wants=network-online.target",
    ]
    # Makes systemd trigger the automount and wait for it before starting the
    # container, and hold it mounted for as long as the service runs — so the
    # share's idle timeout cannot pull the files out from under it.
    lines += [f"RequiresMountsFor={path}" for path in required_mounts]

    lines += ["", "[Container]", f"Image={source.image}"]
    if container_name:
        # Named explicitly so `podman exec` can reach it. Quadlet's default
        # (systemd-<unit>) is an implementation detail not worth depending on.
        lines.append(f"ContainerName={container_name}")
    lines += [
        f"PublishPort={source.port}:{source.port}",
        f"Volume={config_dir}:/config:Z",
    ]
    lines += [f"Volume={volume}" for volume in volumes]
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

    def _resolve_paths(self, values: dict[str, str]) -> dict[str, str]:
        """Canonicalise any answers that are absolute paths.

        On Bazzite /mnt is a symlink to /var/mnt, and RequiresMountsFor has to
        name the real mount unit's path or it matches nothing — the same trap
        the NAS script hit.
        """
        resolved: dict[str, str] = {}
        for key, value in values.items():
            resolved[key] = value
            if not value.startswith("/"):
                continue
            result = self.bridge.run(["realpath", "-m", value], timeout=15, check=False)
            if result.ok and result.output.strip():
                resolved[key] = result.output.strip().splitlines()[0]
        return resolved

    def install(self, on_line: LineCallback) -> None:
        """Write the unit, reload systemd and start the service."""
        values = self._resolve_paths(self.state.app_settings(self.app.id))
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
            build_unit(
                self.app.name,
                self.source,
                values,
                config_dir,
                container_name=self.unit_name,
            ),
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
        self._verify_volumes(values, on_line)

    def _verify_volumes(self, values: dict[str, str], on_line: LineCallback) -> None:
        """Check the service can actually read the folders it was given.

        Worth the extra seconds: a container that binds an idle automount
        sees an empty directory and reports nothing wrong. Without this the
        only symptom is the app "not finding" files, with no clue whether the
        share is empty, unreadable, or simply named differently inside.
        """
        for volume in self.source.volumes:
            resolved = substitute(volume, values)
            host_path, _, rest = resolved.partition(":")
            if not is_external_path(host_path):
                continue
            inside = rest.split(":", 1)[0]

            on_line(f"[ignis] checking {self.app.name} can read your files...")
            self.bridge.run(
                ["bash", "-c", _verify_script(self.unit_name, host_path, inside)],
                on_line=on_line,
                timeout=90,
                check=False,
            )

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
        on_line(f"[ignis] your settings in {data_dir(self.app.id)} have been left alone")
        on_line("[ignis] installing again will pick up where you left off")

    def removable_data(self) -> Path | None:
        """This app's own settings folder, if it has one worth offering to delete."""
        return data_dir(self.app.id)

    def purge(self, on_line: LineCallback) -> None:
        """Uninstall, and delete the app's own settings and database.

        Only ever touches Ignis's own folder for this app. The media folder
        is the user's and is never in scope, whatever else happens.
        """
        self.uninstall(on_line)

        target = data_dir(self.app.id)
        if not is_ignis_data_dir(target):
            raise InstallError(f"Refusing to delete {target}: not an Ignis data folder")

        on_line(f"[ignis] deleting {target}")
        self._run(["rm", "-rf", str(target)], on_line)
        on_line(f"[ignis] {self.app.name} will start fresh next time it is installed")

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

        Only home paths: a media folder on the NAS must already exist —
        creating it here would just mask a missing mount, and would leave the
        container reading an empty local directory instead.
        """
        home = Path.home()
        dirs: list[str] = []
        for volume in self.source.volumes:
            host = substitute(volume, values).split(":", 1)[0]
            if host.startswith("%h/"):
                host = str(home / host[3:])
            if not is_external_path(host):
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
