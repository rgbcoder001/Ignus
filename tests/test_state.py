"""State persistence, atomicity and corruption recovery."""

from __future__ import annotations

import json

from ignis.core.state import CacheEntry, InstalledApp, State


def test_missing_file_starts_fresh(tmp_path):
    state = State.load(tmp_path / "state.json")
    assert state.installed("anything") is None
    assert state.github_pat == ""


def test_round_trips_installed_apps(tmp_path):
    path = tmp_path / "state.json"
    state = State.load(path)
    state.set_installed("zelda", InstalledApp(tag="v1.2.0", files=("/a/b", "/c/d")))
    state.save()

    reloaded = State.load(path)
    record = reloaded.installed("zelda")
    assert record == InstalledApp(tag="v1.2.0", files=("/a/b", "/c/d"))


def test_clear_installed(tmp_path):
    state = State.load(tmp_path / "state.json")
    state.set_installed("zelda", InstalledApp(tag="v1"))
    state.clear_installed("zelda")
    assert state.installed("zelda") is None


def test_round_trips_api_cache(tmp_path):
    path = tmp_path / "state.json"
    state = State.load(path)
    state.set_cache("Owner/Repo", "W/etag123", {"tag_name": "v9"})
    state.save()

    entry = State.load(path).cache("Owner/Repo")
    assert isinstance(entry, CacheEntry)
    assert entry.etag == "W/etag123"
    assert entry.payload == {"tag_name": "v9"}
    assert entry.fetched_at


def test_round_trips_settings(tmp_path):
    path = tmp_path / "state.json"
    state = State.load(path)
    state.github_pat = "  ghp_secret  "
    state.save()
    assert State.load(path).github_pat == "ghp_secret"


def test_corrupt_file_starts_fresh_and_is_preserved(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json at all", encoding="utf-8")

    state = State.load(path)
    assert state.installed("x") is None
    assert (tmp_path / "state.json.corrupt").exists()


def test_non_object_json_starts_fresh(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert State.load(path).github_pat == ""


def test_partial_document_is_repaired(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"settings": {"github_pat": "abc"}}), encoding="utf-8")

    state = State.load(path)
    assert state.github_pat == "abc"
    # Missing sections must not raise on access.
    assert state.installed("x") is None
    assert state.cache("a/b") is None


def test_malformed_records_are_ignored(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps({"github_apps": {"x": "not a dict", "y": {"no": "tag"}}}),
        encoding="utf-8",
    )
    state = State.load(path)
    assert state.installed("x") is None
    assert state.installed("y") is None


def test_save_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "deeper" / "state.json"
    state = State.load(path)
    state.github_pat = "x"
    state.save()
    assert path.exists()


def test_window_geometry_defaults(tmp_path):
    assert State.load(tmp_path / "state.json").window_geometry() == (1000, 700, False)


def test_window_geometry_round_trips(tmp_path):
    path = tmp_path / "state.json"
    state = State.load(path)
    state.set_window_geometry(1280, 820, True)
    state.save()
    assert State.load(path).window_geometry() == (1280, 820, True)


def test_absurd_window_sizes_fall_back_to_the_default(tmp_path):
    """A corrupt size must not produce a window the user cannot use."""
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps({"settings": {"window": {"width": 3, "height": 99999}}}),
        encoding="utf-8",
    )
    assert State.load(path).window_geometry() == (1000, 700, False)


def test_non_integer_window_sizes_are_ignored(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps({"settings": {"window": {"width": "wide", "height": None}}}),
        encoding="utf-8",
    )
    assert State.load(path).window_geometry() == (1000, 700, False)


def test_window_geometry_and_token_coexist(tmp_path):
    path = tmp_path / "state.json"
    state = State.load(path)
    state.github_pat = "ghp_x"
    state.set_window_geometry(900, 640, False)
    state.save()

    reloaded = State.load(path)
    assert reloaded.github_pat == "ghp_x"
    assert reloaded.window_geometry() == (900, 640, False)


def test_save_leaves_no_temp_files(tmp_path):
    path = tmp_path / "state.json"
    state = State.load(path)
    state.save()
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_concurrent_mutation_and_save_do_not_corrupt(tmp_path):
    """Workers write the API cache and install records while the main thread
    saves settings; without State's lock, json.dump can hit 'dictionary
    changed size during iteration'."""
    import threading

    from ignis.core.state import InstalledApp

    path = tmp_path / "state.json"
    state = State.load(path)
    errors: list[BaseException] = []

    def hammer(worker_id: int) -> None:
        try:
            for i in range(150):
                state.set_cache(f"owner/repo-{worker_id}", f"etag-{i}", {"tag_name": f"v{i}"})
                state.set_installed(f"app-{worker_id}", InstalledApp(tag=f"v{i}"))
                state.save()
        except BaseException as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    reloaded = State.load(path)  # the final file must be intact JSON
    assert reloaded.installed("app-0") is not None
