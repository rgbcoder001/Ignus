"""Packaging consistency checks.

The Flatpak build cannot run on a Windows dev machine, so these tests catch
the mistakes that would otherwise only surface in CI: a manifest referencing
a file that moved, or the app id / runtime version drifting apart across the
manifest, desktop file, metainfo, CI workflow and source.
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree

import pytest

yaml = pytest.importorskip("yaml", reason="pyyaml is a dev dependency")

from ignis import APP_ID

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "flatpak" / f"{APP_ID}.yml"
DESKTOP = REPO / "data" / f"{APP_ID}.desktop"
METAINFO = REPO / "data" / f"{APP_ID}.metainfo.xml"
ICON = REPO / "data" / f"{APP_ID}.svg"
BUILD_WORKFLOW = REPO / ".github" / "workflows" / "build.yml"

# Repo-relative paths as they appear in the manifest's build-commands.
PATH_TOKEN = re.compile(r"(?:^|\s)((?:bin|src|data|scripts)/[\w./-]+)")


@pytest.fixture(scope="module")
def manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def test_packaging_files_exist():
    for path in (MANIFEST, DESKTOP, METAINFO, ICON, BUILD_WORKFLOW):
        assert path.is_file(), f"missing packaging file: {path}"


def test_manifest_app_id_matches_source(manifest):
    assert manifest["app-id"] == APP_ID


def test_manifest_command_exists_and_is_installed(manifest):
    assert manifest["command"] == "ignis"
    launcher = REPO / "bin" / "ignis"
    assert launcher.is_file()
    assert launcher.read_text(encoding="utf-8").startswith("#!/bin/sh")


def test_launcher_has_unix_line_endings():
    """A CRLF shebang becomes 'bad interpreter' inside the sandbox."""
    assert b"\r\n" not in (REPO / "bin" / "ignis").read_bytes()


def test_every_path_referenced_by_the_manifest_exists(manifest):
    commands = " ".join(manifest["modules"][0]["build-commands"])
    referenced = {match for match in PATH_TOKEN.findall(commands)}
    assert referenced, "no source paths found in build-commands"
    missing = sorted(str(p) for p in referenced if not (REPO / p).exists())
    assert not missing, f"manifest references missing paths: {missing}"


def test_host_access_permission_is_granted(manifest):
    """Without this, every install fails confusingly (CLAUDE.md gotchas)."""
    assert "--talk-name=org.freedesktop.Flatpak" in manifest["finish-args"]


def test_network_permission_is_granted(manifest):
    assert "--share=network" in manifest["finish-args"]


def test_ci_image_matches_the_manifest_runtime(manifest):
    """A mismatched SDK image breaks the build (CLAUDE.md gotchas)."""
    workflow = yaml.safe_load(BUILD_WORKFLOW.read_text(encoding="utf-8"))
    image = workflow["jobs"]["bundle"]["container"]["image"]
    assert image.endswith(f":gnome-{manifest['runtime-version']}")


def test_ci_builds_the_manifest_we_ship(manifest):
    workflow = yaml.safe_load(BUILD_WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["bundle"]["steps"]
    paths = [s.get("with", {}).get("manifest-path") for s in steps]
    assert MANIFEST.relative_to(REPO).as_posix() in paths


def test_desktop_entry_is_consistent():
    fields = dict(
        line.split("=", 1)
        for line in DESKTOP.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    assert fields["Exec"] == "ignis"
    assert fields["Icon"] == APP_ID
    assert fields["Terminal"] == "false"


def test_metainfo_is_valid_xml_and_consistent():
    root = ElementTree.parse(METAINFO).getroot()
    assert root.tag == "component"
    assert root.findtext("id") == APP_ID
    assert root.findtext("launchable") == f"{APP_ID}.desktop"
    assert root.findtext("name")
    assert root.findtext("summary")
    assert root.find("releases/release") is not None


def test_metainfo_explains_host_access():
    """Flathub reviewers will ask why the app can run host commands."""
    text = METAINFO.read_text(encoding="utf-8").lower()
    assert "host" in text and "command" in text


def test_icon_is_valid_svg():
    root = ElementTree.parse(ICON).getroot()
    assert root.tag.endswith("svg")
