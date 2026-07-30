"""Catalog parsing and validation."""

from __future__ import annotations

import tomllib

import pytest

from ignis.core.catalog import (
    Category,
    CatalogError,
    FlathubSource,
    GithubSource,
    InstallKind,
    ScriptSource,
    UjustSource,
    load_catalog,
    parse_catalog,
)

VALID = """
[[apps]]
id = "heroic"
name = "Heroic Games Launcher"
summary = "Play your Epic and GOG games"
description = "Longer text."
category = "gaming"
hardware = []

[apps.source]
type = "flathub"
ref = "com.heroicgameslauncher.hgl"
"""


def parse(text: str):
    """Parse a TOML fragment into apps."""
    return parse_catalog(tomllib.loads(text))


def test_parses_a_valid_flathub_entry():
    (app,) = parse(VALID)
    assert app.id == "heroic"
    assert app.category is Category.GAMING
    assert app.description == "Longer text."
    assert isinstance(app.source, FlathubSource)
    assert app.source.ref == "com.heroicgameslauncher.hgl"


def test_parses_every_source_type():
    text = """
[[apps]]
id = "a"
name = "A"
summary = "s"
category = "emulation"
[apps.source]
type = "ujust"
recipe = "install-emudeck"
check_cmd = ["test", "-d", "/tmp"]

[[apps]]
id = "b"
name = "B"
summary = "s"
category = "emulation"
[apps.source]
type = "github"
repo = "Owner/Repo"
asset_pattern = '(?i)linux.*\\.appimage$'
install_kind = "appimage"

[[apps]]
id = "c"
name = "C"
summary = "s"
category = "system"
[apps.source]
type = "script"
file = "scripts/fix.sh"
"""
    a, b, c = parse(text)
    assert isinstance(a.source, UjustSource)
    assert a.source.check_cmd == ("test", "-d", "/tmp")
    assert isinstance(b.source, GithubSource)
    assert b.source.install_kind is InstallKind.APPIMAGE
    assert b.source.matches("App-linux-x64.AppImage")
    assert not b.source.matches("App-windows.zip")
    assert isinstance(c.source, ScriptSource)


@pytest.mark.parametrize(
    "entry",
    [
        'id = "x"\nname = "X"\ncategory = "gaming"\n[apps.source]\ntype="flathub"\nref="a"',
        'id = "X_bad"\nname = "X"\nsummary = "s"\ncategory = "gaming"\n[apps.source]\ntype="flathub"\nref="a"',
        'id = "x"\nname = "X"\nsummary = "s"\ncategory = "nope"\n[apps.source]\ntype="flathub"\nref="a"',
        'id = "x"\nname = "X"\nsummary = "s"\ncategory = "gaming"\nhardware = ["s3"]\n[apps.source]\ntype="flathub"\nref="a"',
        'id = "x"\nname = "X"\nsummary = "s"\ncategory = "gaming"\n[apps.source]\ntype="mystery"',
        'id = "x"\nname = "X"\nsummary = "s"\ncategory = "gaming"',
        'id = "x"\nname = "X"\nsummary = "s"\ncategory = "gaming"\n[apps.source]\ntype="github"\nrepo="notaslug"\nasset_pattern="x"\ninstall_kind="appimage"',
        'id = "x"\nname = "X"\nsummary = "s"\ncategory = "gaming"\n[apps.source]\ntype="github"\nrepo="a/b"\nasset_pattern="[unclosed"\ninstall_kind="appimage"',
        'id = "x"\nname = "X"\nsummary = "s"\ncategory = "gaming"\n[apps.source]\ntype="github"\nrepo="a/b"\nasset_pattern="x"\ninstall_kind="msi"',
        'id = "x"\nname = "X"\nsummary = "s"\ncategory = "gaming"\n[apps.source]\ntype="script"\nfile="/etc/evil.sh"',
        'id = "x"\nname = "X"\nsummary = "s"\ncategory = "gaming"\n[apps.source]\ntype="script"\nfile="../../evil.sh"',
    ],
    ids=[
        "missing-summary",
        "bad-id",
        "unknown-category",
        "unknown-vendor",
        "unknown-source",
        "missing-source",
        "bad-repo",
        "bad-regex",
        "bad-install-kind",
        "absolute-script",
        "escaping-script",
    ],
)
def test_bad_entry_is_skipped_not_fatal(entry):
    """One bad entry must never take down the app (CLAUDE.md rule 8)."""
    assert parse(f"[[apps]]\n{entry}\n") == []


def test_bad_entry_does_not_hide_good_ones():
    text = VALID + '\n[[apps]]\nid = "broken"\ncategory = "gaming"\n'
    apps = parse(text)
    assert [app.id for app in apps] == ["heroic"]


def test_duplicate_ids_are_skipped():
    apps = parse(VALID + VALID)
    assert len(apps) == 1


def test_hardware_filtering():
    text = """
[[apps]]
id = "lact"
name = "LACT"
summary = "s"
category = "system"
hardware = ["amd"]
[apps.source]
type = "flathub"
ref = "io.github.lact"
"""
    (app,) = parse(text)
    assert app.supports(frozenset({"amd"}))
    assert app.supports(frozenset({"amd", "intel"}))
    assert not app.supports(frozenset({"nvidia"}))
    # Detection failure must never hide apps.
    assert app.supports(frozenset())


def test_catalog_without_apps_table_raises():
    with pytest.raises(CatalogError):
        parse("title = 'nope'")


def test_missing_file_raises_catalog_error(tmp_path):
    with pytest.raises(CatalogError):
        load_catalog(tmp_path / "nope.toml")


def test_malformed_toml_raises_catalog_error(tmp_path):
    path = tmp_path / "catalog.toml"
    path.write_text("[[apps]\nbroken", encoding="utf-8")
    with pytest.raises(CatalogError):
        load_catalog(path)
