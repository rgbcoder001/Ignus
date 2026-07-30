"""GPU detection against a fake sysfs tree."""

from __future__ import annotations

from pathlib import Path

from ignis.core.hardware import detect_gpu_vendors, label


def make_card(root: Path, name: str, vendor_id: str | None) -> None:
    """Create a fake /sys/class/drm entry."""
    device = root / "sys" / "class" / "drm" / name / "device"
    device.mkdir(parents=True)
    if vendor_id is not None:
        (device / "vendor").write_text(f"{vendor_id}\n", encoding="utf-8")


def test_detects_amd(tmp_path):
    make_card(tmp_path, "card0", "0x1002")
    assert detect_gpu_vendors(tmp_path) == frozenset({"amd"})


def test_detects_hybrid_igpu_and_dgpu(tmp_path):
    make_card(tmp_path, "card0", "0x8086")
    make_card(tmp_path, "card1", "0x10de")
    assert detect_gpu_vendors(tmp_path) == frozenset({"intel", "nvidia"})


def test_ignores_connector_entries(tmp_path):
    make_card(tmp_path, "card0", "0x1002")
    make_card(tmp_path, "card0-HDMI-A-1", "0x10de")
    assert detect_gpu_vendors(tmp_path) == frozenset({"amd"})


def test_unknown_vendor_id_is_ignored(tmp_path):
    make_card(tmp_path, "card0", "0xbeef")
    assert detect_gpu_vendors(tmp_path) == frozenset()


def test_missing_vendor_file_is_ignored(tmp_path):
    make_card(tmp_path, "card0", None)
    assert detect_gpu_vendors(tmp_path) == frozenset()


def test_missing_drm_directory_returns_empty(tmp_path):
    """No sysfs (e.g. on Windows) must not raise."""
    assert detect_gpu_vendors(tmp_path) == frozenset()


def test_labels():
    assert label("amd") == "AMD"
    assert label("nvidia") == "NVIDIA"
