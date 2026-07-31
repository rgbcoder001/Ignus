"""Building and reading .desktop entries."""

from __future__ import annotations

import pytest

from ignis.core.catalog import Category
from ignis.core.desktop import (
    build_entry,
    categories_for,
    entry_app_id,
    parse_exec,
    quote_exec,
)


def test_quote_exec_uses_double_quotes():
    """The desktop spec allows double quotes only — never shlex's singles."""
    assert quote_exec(["/opt/My App/run"]) == '"/opt/My App/run"'


def test_quote_exec_escapes_quotes_and_backslashes():
    assert quote_exec(['/tmp/od"d']) == '"/tmp/od\\"d"'
    assert quote_exec([r"/tmp/back\slash"]) == '"/tmp/back\\\\slash"'


def test_quote_exec_joins_arguments():
    assert quote_exec(["flatpak", "run", "org.x.Y"]) == '"flatpak" "run" "org.x.Y"'


def test_round_trips_through_parse_exec():
    argv = ["flatpak", "run", "com.obsproject.Studio"]
    entry = build_entry(
        name="OBS",
        comment="Record",
        exec_argv=argv,
        icon="com.obsproject.Studio",
        categories="AudioVideo;",
        app_id="obs",
    )
    assert parse_exec(entry) == argv


def test_round_trips_a_path_with_spaces():
    argv = ["/home/me/Applications/My App/run"]
    entry = build_entry(
        name="X", comment="", exec_argv=argv, icon="x", categories="Game;", app_id="x"
    )
    assert parse_exec(entry) == argv


def test_parse_exec_strips_field_codes():
    assert parse_exec('Exec="/usr/bin/mpv" %U\n') == ["/usr/bin/mpv"]
    assert parse_exec("Exec=/usr/bin/foo %f %i\n") == ["/usr/bin/foo"]


def test_parse_exec_without_an_exec_line():
    assert parse_exec("[Desktop Entry]\nName=X\n") is None


def test_parse_exec_of_an_empty_value():
    assert parse_exec("Exec=\n") is None


def test_parse_exec_of_unbalanced_quotes_is_none_not_a_crash():
    assert parse_exec('Exec="/broken\n') is None


def test_build_entry_includes_the_expected_keys():
    entry = build_entry(
        name="EmuDeck",
        comment="Emulation",
        exec_argv=["/x"],
        icon="icon",
        categories="Game;Emulator;",
        app_id="emudeck",
        working_directory="/home/me",
    )
    assert "[Desktop Entry]" in entry
    assert "Name=EmuDeck" in entry
    assert "Comment=Emulation" in entry
    assert "Categories=Game;Emulator;" in entry
    assert "Path=/home/me" in entry
    assert "Terminal=false" in entry
    assert "X-Ignis-App=emudeck" in entry


def test_working_directory_is_optional():
    entry = build_entry(
        name="X", comment="", exec_argv=["/x"], icon="i", categories="Game;", app_id="x"
    )
    assert "Path=" not in entry


def test_entry_app_id_identifies_our_own_files():
    entry = build_entry(
        name="X", comment="", exec_argv=["/x"], icon="i", categories="Game;", app_id="obs"
    )
    assert entry_app_id(entry) == "obs"


def test_entry_app_id_of_a_foreign_file_is_none():
    assert entry_app_id("[Desktop Entry]\nName=Someone Else\nExec=/bin/true\n") is None


@pytest.mark.parametrize("category", list(Category))
def test_every_category_maps_to_menu_categories(category):
    value = categories_for(category)
    assert value.endswith(";")
