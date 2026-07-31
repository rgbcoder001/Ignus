"""ContainerProvider: Quadlet unit generation and service lifecycle."""

from __future__ import annotations

import base64
import re
from pathlib import Path, PurePosixPath

import pytest

from fake_bridge import FakeBridge
from ignis.core.catalog import App, Category, ContainerSource
from ignis.core.state import State
from ignis.providers.base import InstallStatus
from ignis.providers.container import ContainerProvider, build_unit, data_dir

SOURCE = ContainerSource(
    image="docker.io/gotson/komga:latest",
    port=25600,
    volumes=("{books_dir}:/books:ro",),
)


@pytest.fixture
def state(tmp_path) -> State:
    return State.load(tmp_path / "state.json")


@pytest.fixture
def bridge() -> FakeBridge:
    return FakeBridge()


@pytest.fixture
def app() -> App:
    return App(
        id="komga",
        name="Komga",
        summary="Comics server",
        category=Category.MEDIA,
        source=SOURCE,
    )


# -- unit generation ----------------------------------------------------


def test_unit_has_the_sections_quadlet_needs():
    unit = build_unit("Komga", SOURCE, {"books_dir": "/mnt/nas"}, Path("/cfg"))
    assert "[Unit]" in unit
    assert "[Container]" in unit
    assert "[Install]" in unit
    assert "Image=docker.io/gotson/komga:latest" in unit
    assert "PublishPort=25600:25600" in unit


def test_unit_substitutes_the_users_answer():
    unit = build_unit("Komga", SOURCE, {"books_dir": "/mnt/nas/Books"}, Path("/cfg"))
    assert "Volume=/mnt/nas/Books:/books:ro" in unit


def test_media_volume_stays_read_only():
    """A server has no business writing to someone's library."""
    unit = build_unit("Komga", SOURCE, {"books_dir": "/mnt/nas"}, Path("/cfg"))
    media = [ln for ln in unit.splitlines() if "/books" in ln]
    assert media and all(ln.endswith(":ro") for ln in media)


def test_config_volume_is_writable():
    """Its own database has to be writable, unlike the library."""
    config = PurePosixPath("/home/me/.local/share/ignis/komga")
    unit = build_unit("Komga", SOURCE, {}, config)
    assert f"Volume={config}:/config:Z" in unit


def test_unit_restarts_on_failure():
    assert "Restart=on-failure" in build_unit("K", SOURCE, {}, Path("/cfg"))


def test_environment_entries_are_included():
    source = ContainerSource(image="img", port=1, environment=("TZ={tz}",))
    unit = build_unit("X", source, {"tz": "Europe/London"}, Path("/cfg"))
    assert "Environment=TZ=Europe/London" in unit


# -- lifecycle ----------------------------------------------------------


def test_status_follows_the_service(app, bridge, state):
    unit = ["systemctl", "--user", "is-active", "ignis-komga.service"]
    bridge.set_result(unit, returncode=0)
    assert ContainerProvider(app, bridge, state).status() is InstallStatus.INSTALLED

    bridge.set_result(unit, returncode=3)
    assert ContainerProvider(app, bridge, state).status() is InstallStatus.NOT_INSTALLED


def test_install_writes_the_unit_and_starts_it(app, bridge, state):
    state.set_app_settings("komga", {"books_dir": "/mnt/nas/Books"})
    ContainerProvider(app, bridge, state).install(lambda _l: None)

    commands = [" ".join(c.argv) for c in bridge.calls]
    assert any("base64 -d" in c for c in commands), "unit was never written"
    assert any("daemon-reload" in c for c in commands)
    assert any("start ignis-komga.service" in c for c in commands)


def test_install_sends_the_unit_intact(app, bridge, state):
    """The unit travels base64'd, so quoting can never corrupt it."""
    state.set_app_settings("komga", {"books_dir": "/mnt/nas/Books"})
    ContainerProvider(app, bridge, state).install(lambda _l: None)

    write = next(c for c in bridge.calls if "base64 -d" in " ".join(c.argv))
    # shlex.quote leaves base64 unquoted: every character in it is shell-safe.
    match = re.search(r"printf %s '?([A-Za-z0-9+/=]+)'?", write.argv[2])
    assert match, f"could not find the payload in: {write.argv[2]}"
    decoded = base64.b64decode(match.group(1)).decode()
    assert "Volume=/mnt/nas/Books:/books:ro" in decoded
    assert "[Container]" in decoded


def test_uninstall_removes_the_unit_but_not_the_data(app, bridge, state):
    lines: list[str] = []
    ContainerProvider(app, bridge, state).uninstall(lines.append)

    commands = [" ".join(c.argv) for c in bridge.calls]
    assert any("stop ignis-komga.service" in c for c in commands)
    assert any("rm -f" in c and "ignis-komga.container" in c for c in commands)

    # The library and the database must survive being uninstalled.
    assert not any("rm" in c and str(data_dir("komga")) in c for c in commands)
    assert any("left alone" in line for line in lines)


def test_launch_opens_the_web_interface(app, bridge, state):
    assert ContainerProvider(app, bridge, state).launch_command() == [
        "xdg-open",
        "http://localhost:25600",
    ]


def test_preview_names_the_unit_and_address(app, bridge, state):
    preview = ContainerProvider(app, bridge, state).command_preview()
    assert "ignis-komga" in preview
    assert "25600" in preview
