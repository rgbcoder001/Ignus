"""Per-app setup questions: parsing, storage and substitution."""

from __future__ import annotations

import tomllib

import pytest

from ignis.core.catalog import ContainerSource, SettingType, parse_catalog
from ignis.core.state import State
from ignis.providers.base import shell_preamble, substitute

NAS = """
[[apps]]
id = "nas-mount"
name = "Connect to a NAS"
summary = "Reach files on your network drive"
category = "system"

[apps.source]
type = "script"
file = "nas-mount.sh"

[[apps.settings]]
key = "nas_host"
label = "NAS address"
help = "For example 192.168.1.50"

[[apps.settings]]
key = "mount_point"
label = "Show it as"
type = "path"
default = "/mnt/nas"
"""


def parse(text: str):
    return parse_catalog(tomllib.loads(text))


# -- catalog ------------------------------------------------------------


def test_parses_settings():
    (app,) = parse(NAS)
    assert [s.key for s in app.settings] == ["nas_host", "mount_point"]
    assert app.settings[0].type is SettingType.TEXT
    assert app.settings[1].type is SettingType.PATH
    assert app.settings[1].default == "/mnt/nas"
    assert app.settings[0].help


def test_apps_without_settings_have_none():
    text = NAS.split("[[apps.settings]]")[0]
    (app,) = parse(text)
    assert app.settings == ()


@pytest.mark.parametrize(
    "block",
    [
        '[[apps.settings]]\nlabel = "No key"',
        '[[apps.settings]]\nkey = "ok"',
        '[[apps.settings]]\nkey = "Bad-Key"\nlabel = "x"',
        '[[apps.settings]]\nkey = "ok"\nlabel = "x"\ntype = "mystery"',
        '[[apps.settings]]\nkey = "dup"\nlabel = "a"\n[[apps.settings]]\nkey = "dup"\nlabel = "b"',
    ],
    ids=["no-key", "no-label", "bad-key", "bad-type", "duplicate-key"],
)
def test_bad_settings_skip_the_entry_without_crashing(block):
    base = NAS.split("[[apps.settings]]")[0]
    assert parse(base + block) == []


def test_parses_container_source():
    text = """
[[apps]]
id = "komga"
name = "Komga"
summary = "Comics server"
category = "media"

[apps.source]
type = "container"
image = "docker.io/gotson/komga:latest"
port = 25600
volumes = ["{books_dir}:/books:ro"]
"""
    (app,) = parse(text)
    assert isinstance(app.source, ContainerSource)
    assert app.source.port == 25600
    assert app.source.volumes == ("{books_dir}:/books:ro",)


@pytest.mark.parametrize("port", ["0", "70000", '"25600"', "true"])
def test_bad_container_port_skips_the_entry(port):
    text = f"""
[[apps]]
id = "x"
name = "X"
summary = "s"
category = "media"
[apps.source]
type = "container"
image = "img"
port = {port}
"""
    assert parse(text) == []


# -- substitution -------------------------------------------------------


def test_substitute_replaces_placeholders():
    assert substitute("{a}/books:ro", {"a": "/mnt/nas"}) == "/mnt/nas/books:ro"


def test_substitute_leaves_unknown_placeholders_alone():
    """An unanswered question must not silently become an empty path."""
    assert substitute("{missing}/x", {}) == "{missing}/x"


def test_substitute_tolerates_braces_in_the_text():
    """Unit files and scripts contain braces of their own; format() would choke."""
    assert substitute("${HOME} {a}", {"a": "1"}) == "${HOME} 1"


def test_shell_preamble_quotes_values():
    preamble = shell_preamble({"path": "/mnt/my media", "host": "192.168.1.5"})
    assert "path='/mnt/my media'" in preamble
    assert preamble.endswith("\n")


def test_shell_preamble_neutralises_injection():
    """An answer must not be able to run commands of its own."""
    preamble = shell_preamble({"host": "x'; rm -rf /; echo '"})
    assert "rm -rf /" in preamble  # present, but quoted
    assert preamble.count("'\"'\"'") or "'" in preamble
    assert not preamble.startswith("host=x;")


def test_shell_preamble_of_nothing_is_empty():
    assert shell_preamble({}) == ""


# -- storage ------------------------------------------------------------


def test_app_settings_round_trip(tmp_path):
    path = tmp_path / "state.json"
    state = State.load(path)
    state.set_app_settings("nas-mount", {"nas_host": "192.168.1.50"})
    state.save()
    assert State.load(path).app_settings("nas-mount") == {"nas_host": "192.168.1.50"}


def test_app_settings_default_to_empty(tmp_path):
    assert State.load(tmp_path / "state.json").app_settings("nope") == {}


def test_clearing_app_settings(tmp_path):
    state = State.load(tmp_path / "state.json")
    state.set_app_settings("x", {"a": "b"})
    state.clear_app_settings("x")
    assert state.app_settings("x") == {}


def test_malformed_stored_settings_are_ignored(tmp_path):
    import json

    path = tmp_path / "state.json"
    path.write_text(json.dumps({"app_settings": {"x": "not a dict"}}), encoding="utf-8")
    assert State.load(path).app_settings("x") == {}
