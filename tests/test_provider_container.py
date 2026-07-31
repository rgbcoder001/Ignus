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
    """A server has no business writing to someone's library.

    Checks the options rather than the end of the line: propagation settings
    are appended after ro, so the volume reads ":ro,rslave".
    """
    unit = build_unit("Komga", SOURCE, {"books_dir": "/mnt/nas"}, Path("/cfg"))
    media = [ln for ln in unit.splitlines() if "/books" in ln]
    assert media
    for line in media:
        options = line.split(":")[-1].split(",")
        assert "ro" in options, line
        assert "rw" not in options, line


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


# -- automounted network shares -----------------------------------------


def test_network_volume_gets_slave_propagation():
    """Podman's default rprivate means a container started while an
    automounted share is idle binds an empty directory and can never see the
    files appear. rslave lets the host's mount propagate in."""
    unit = build_unit("Komga", SOURCE, {"books_dir": "/var/mnt/nas"}, Path("/cfg"))
    volume = next(ln for ln in unit.splitlines() if "/books" in ln)
    assert volume.endswith(":ro,rslave"), volume


def test_network_volume_is_required_before_start():
    """RequiresMountsFor makes systemd trigger the automount and wait, and
    holds it mounted while the service runs so the idle timeout cannot pull
    the files away underneath it."""
    unit = build_unit("Komga", SOURCE, {"books_dir": "/var/mnt/nas"}, Path("/cfg"))
    assert "RequiresMountsFor=/var/mnt/nas" in unit


def test_config_volume_gets_no_propagation_or_dependency():
    """Ignis's own config folder is an ordinary directory, not a mount."""
    unit = build_unit("Komga", SOURCE, {"books_dir": "/var/mnt/nas"}, Path("/cfg"))
    config = next(ln for ln in unit.splitlines() if "/config" in ln)
    assert "rslave" not in config
    assert "RequiresMountsFor=/cfg" not in unit


def test_home_volume_is_not_treated_as_a_network_mount():
    source = ContainerSource(
        image="img",
        port=1,
        volumes=(f"{Path.home()}/.local/share/ignis/x/cache:/cache:Z",),
    )
    unit = build_unit("X", source, {}, Path("/cfg"))
    assert "rslave" not in unit
    assert "RequiresMountsFor" not in unit


def test_propagation_is_not_added_twice():
    source = ContainerSource(image="img", port=1, volumes=("/mnt/n:/d:ro,rslave",))
    unit = build_unit("X", source, {}, Path("/cfg"))
    assert unit.count("rslave") == 1


def test_propagation_on_a_volume_without_options():
    from ignis.providers.container import with_propagation

    assert with_propagation("/mnt/n:/d") == "/mnt/n:/d:rslave"
    assert with_propagation("/mnt/n:/d:ro") == "/mnt/n:/d:ro,rslave"


def test_install_canonicalises_paths_before_writing_the_unit(app, bridge, state):
    """/mnt is a symlink to /var/mnt on Bazzite; RequiresMountsFor naming the
    symlink would match no mount unit at all."""
    state.set_app_settings("komga", {"books_dir": "/mnt/nas"})
    bridge.set_result(["realpath", "-m", "/mnt/nas"], output="/var/mnt/nas")

    ContainerProvider(app, bridge, state).install(lambda _l: None)

    write = next(c for c in bridge.calls if "base64 -d" in " ".join(c.argv))
    match = re.search(r"printf %s '?([A-Za-z0-9+/=]+)'?", write.argv[2])
    decoded = base64.b64decode(match.group(1)).decode()
    assert "RequiresMountsFor=/var/mnt/nas" in decoded
    assert "Volume=/var/mnt/nas:/books:ro,rslave" in decoded


def test_install_says_what_the_folder_is_called_inside(app, bridge, state):
    """Komga's own setup asks for a path, and it is /books in there, not the
    path the user typed."""
    state.set_app_settings("komga", {"books_dir": "/var/mnt/nas"})
    lines: list[str] = []
    ContainerProvider(app, bridge, state).install(lines.append)
    assert any("/books" in line and "called" in line for line in lines)


# -- placeholder guard --------------------------------------------------


def test_unanswered_placeholder_is_an_error_not_a_literal_directory(app, bridge, state):
    """A catalog typo must not put a folder named {books_dir} on disk."""
    from ignis.providers.base import InstallError

    with pytest.raises(InstallError) as excinfo:
        ContainerProvider(app, bridge, state).install(lambda _l: None)
    assert "{books_dir}" in str(excinfo.value)
    assert bridge.calls == []  # nothing was written or started


def test_unresolved_placeholders_helper():
    from ignis.providers.container import unresolved_placeholders

    assert unresolved_placeholders(SOURCE, {}) == ["{books_dir}"]
    assert unresolved_placeholders(SOURCE, {"books_dir": "/mnt/nas"}) == []


# -- lingering ----------------------------------------------------------


def linger_bridge(state_value: str) -> FakeBridge:
    bridge = FakeBridge()
    bridge.set_result(["id", "-un"], output="bazzite")
    bridge.set_result(
        ["loginctl", "show-user", "bazzite", "--property=Linger"],
        output=f"Linger={state_value}",
    )
    return bridge


def test_lingering_already_on_skips_the_password_prompt(app, state):
    """Reinstalling must not ask for a password it does not need."""
    bridge = linger_bridge("yes")
    state.set_app_settings("komga", {"books_dir": "/mnt/nas"})
    ContainerProvider(app, bridge, state).install(lambda _l: None)

    assert not any(c.argv[0] == "pkexec" for c in bridge.calls)


def test_lingering_off_triggers_the_one_time_prompt(app, state):
    bridge = linger_bridge("no")
    state.set_app_settings("komga", {"books_dir": "/mnt/nas"})
    ContainerProvider(app, bridge, state).install(lambda _l: None)

    assert any(
        c.argv[:3] == ["pkexec", "loginctl", "enable-linger"] for c in bridge.calls
    )


# -- home volume pre-creation -------------------------------------------


def test_home_cache_volume_is_created_before_start(state, bridge):
    """A %h cache volume is created as the user, so Podman never has to."""
    source = ContainerSource(
        image="docker.io/jellyfin/jellyfin:latest",
        port=8096,
        volumes=("{media_dir}:/media:ro", "%h/.local/share/ignis/js/cache:/cache:Z"),
    )
    app = App(id="js", name="JS", summary="s", category=Category.MEDIA, source=source)
    state.set_app_settings("js", {"media_dir": "/mnt/nas"})

    ContainerProvider(app, bridge, state).install(lambda _l: None)

    expected = str(Path.home() / ".local/share/ignis/js/cache")
    mkdirs = [c.argv for c in bridge.calls if c.argv[:2] == ["mkdir", "-p"]]
    assert any(call[2] == expected for call in mkdirs)
    # The media folder is the NAS's own; Ignis must never create it.
    assert not any("/mnt/nas" in call[2] for call in mkdirs)


def test_media_volume_outside_home_is_never_created(app, bridge, state):
    state.set_app_settings("komga", {"books_dir": "/mnt/nas/Books"})
    ContainerProvider(app, bridge, state).install(lambda _l: None)
    mkdirs = [c.argv for c in bridge.calls if c.argv[:2] == ["mkdir", "-p"]]
    assert not any("/mnt/nas" in call[2] for call in mkdirs)
