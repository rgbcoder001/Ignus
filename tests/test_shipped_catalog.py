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
