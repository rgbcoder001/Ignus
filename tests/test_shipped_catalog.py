"""The catalog we ship must parse with nothing skipped."""

from __future__ import annotations

import tomllib

from ignis.core import paths
from ignis.core.catalog import Category, load_catalog


def test_shipped_catalog_loads_completely():
    path = paths.catalog_path()
    raw_count = len(tomllib.loads(path.read_text(encoding="utf-8"))["apps"])
    apps = load_catalog(path)
    assert len(apps) == raw_count, "some shipped catalog entries were skipped"


def test_shipped_catalog_has_content_in_every_category():
    apps = load_catalog(paths.catalog_path())
    covered = {app.category for app in apps}
    assert covered == set(Category)


def test_shipped_catalog_ids_are_unique():
    apps = load_catalog(paths.catalog_path())
    ids = [app.id for app in apps]
    assert len(ids) == len(set(ids))


def test_every_app_explains_itself():
    """Descriptions are the product here: the audience is someone new to
    Linux deciding whether they want this app at all."""
    for app in load_catalog(paths.catalog_path()):
        assert app.description, f"{app.id} has no description"
        assert len(app.description) >= 120, (
            f"{app.id}'s description is too thin to help someone decide"
        )
        assert app.summary, f"{app.id} has no summary"
        assert len(app.summary) <= 60, (
            f"{app.id}'s summary is too long for a list row: {app.summary!r}"
        )


def test_summaries_are_not_just_the_app_name():
    """A summary has to say what the thing does, not repeat its title."""
    for app in load_catalog(paths.catalog_path()):
        assert app.summary.strip().lower() != app.name.strip().lower()


def test_every_script_entry_points_at_a_real_script():
    """A typo'd filename would otherwise only surface when someone clicks
    Install on the actual machine."""
    from ignis.core.catalog import ScriptSource
    from ignis.providers.base import resolve_script

    for app in load_catalog(paths.catalog_path()):
        if isinstance(app.source, ScriptSource):
            script = resolve_script(app.source.file)
            assert script.is_file(), f"{app.id} references a missing script: {script}"
        if app.post_install:
            script = resolve_script(app.post_install)
            assert script.is_file(), f"{app.id} post_install is missing: {script}"


def test_bundled_scripts_are_not_left_half_written():
    """Every bundled script should be a runnable bash script."""
    for script in sorted(paths.scripts_dir().glob("*.sh")):
        text = script.read_text(encoding="utf-8")
        assert text.startswith("#!"), f"{script.name} has no shebang"
        assert "\r\n" not in text, f"{script.name} has CRLF line endings"


def test_nas_script_never_interpolates_user_input_into_the_root_shell():
    """Canary for the pkexec injection fixed in v0.7.0: the -c body must be
    single-quoted, with user data arriving only as positional arguments. A
    ${mount_point} interpolated into the root command string let a crafted
    answer run arbitrary code as root."""
    text = (paths.scripts_dir() / "nas-mount.sh").read_text(encoding="utf-8")

    start = text.index("pkexec /usr/bin/bash -c ")
    body_start = start + len("pkexec /usr/bin/bash -c ")
    assert text[body_start] == "'", "the pkexec -c body must be single-quoted"
    body = text[body_start + 1 : text.index("'", body_start + 1)]
    assert "${mount_point}" not in body
    assert "${UNIT_NAME}" not in body
    assert "$1" in body or '"$1"' in body  # data arrives as arguments


def test_container_entries_keep_their_media_volumes_read_only():
    """A server has no business writing to someone's library, whatever the
    NFS export allows."""
    from ignis.core.catalog import ContainerSource

    for app in load_catalog(paths.catalog_path()):
        if not isinstance(app.source, ContainerSource):
            continue
        media = [v for v in app.source.volumes if "{" in v]
        assert media, f"{app.id} has no user-configured media volume"
        for volume in media:
            assert volume.endswith(":ro"), (
                f"{app.id} mounts {volume} writable — the library must be :ro"
            )


def test_every_ujust_entry_specifies_a_non_interactive_action():
    """A ujust recipe with no action opens a menu needing a terminal, which
    Ignis cannot answer — it either fails or, worse, exits 0 having done
    nothing. Every shipped recipe must name its action explicitly."""
    from ignis.core.catalog import UjustSource

    for app in load_catalog(paths.catalog_path()):
        if isinstance(app.source, UjustSource):
            assert app.source.args, (
                f"{app.id} runs `ujust {app.source.recipe}` with no action "
                "and would drop into an interactive menu"
            )
