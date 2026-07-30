"""Parsing hardware details out of /proc, lspci and os-release."""

from __future__ import annotations

import pytest

from ignis.core.sysinfo import (
    parse_cpu_model,
    parse_gpu_models,
    parse_memory_total,
    parse_os_name,
)

CPUINFO = """processor\t: 0
vendor_id\t: AuthenticAMD
cpu family\t: 25
model name\t: AMD Ryzen 7 7800X3D 8-Core Processor
stepping\t: 2
processor\t: 1
model name\t: AMD Ryzen 7 7800X3D 8-Core Processor
"""

# Real-world shapes for all three vendors.
LSPCI = """00:02.0 Host bridge: Intel Corporation Device 7a04 (rev 11)
03:00.0 VGA compatible controller: Advanced Micro Devices, Inc. [AMD/ATI] Navi 32 [Radeon RX 7700 XT / 7800 XT] (rev c8)
00:1f.3 Audio device: Intel Corporation Raptor Lake HD Audio
"""

LSPCI_HYBRID = """00:02.0 VGA compatible controller: Intel Corporation Raptor Lake-P [Iris Xe Graphics] (rev 04)
01:00.0 3D controller: NVIDIA Corporation GA107M [GeForce RTX 4060 Max-Q] (rev a1)
"""


def test_parses_cpu_model():
    assert parse_cpu_model(CPUINFO) == "AMD Ryzen 7 7800X3D 8-Core Processor"


def test_cpu_model_missing_is_empty_not_an_error():
    assert parse_cpu_model("processor\t: 0\n") == ""
    assert parse_cpu_model("") == ""


def test_parses_arm_style_cpuinfo():
    assert parse_cpu_model("Hardware\t: Rockchip RK3588\n") == "Rockchip RK3588"


def test_parses_memory_total():
    assert parse_memory_total("MemTotal:       32793612 kB\n") == "31 GB"


@pytest.mark.parametrize("text", ["", "MemTotal:\n", "MemTotal:  banana kB\n"])
def test_bad_memory_lines_are_empty_not_an_error(text):
    assert parse_memory_total(text) == ""


def test_parses_os_pretty_name():
    text = 'NAME="Bazzite"\nPRETTY_NAME="Bazzite 44 (FROM Fedora Linux)"\nID=bazzite\n'
    assert parse_os_name(text) == "Bazzite 44 (FROM Fedora Linux)"


def test_missing_pretty_name_is_empty():
    assert parse_os_name("ID=bazzite\n") == ""


def test_picks_the_marketing_gpu_name():
    """The recognisable name is the last bracketed group, not the vendor."""
    assert parse_gpu_models(LSPCI) == ("Radeon RX 7700 XT / 7800 XT",)


def test_finds_both_gpus_on_a_hybrid_laptop():
    assert parse_gpu_models(LSPCI_HYBRID) == (
        "Iris Xe Graphics",
        "GeForce RTX 4060 Max-Q",
    )


def test_ignores_non_graphics_devices():
    models = parse_gpu_models(LSPCI)
    assert not any("Audio" in m or "Host bridge" in m for m in models)


def test_falls_back_to_the_full_name_without_brackets():
    line = "03:00.0 VGA compatible controller: Some Vendor Graphics 9000 (rev 01)\n"
    assert parse_gpu_models(line) == ("Some Vendor Graphics 9000",)


def test_strips_the_revision_suffix():
    assert all("rev" not in m for m in parse_gpu_models(LSPCI))


def test_duplicate_devices_are_listed_once():
    doubled = LSPCI + LSPCI
    assert len(parse_gpu_models(doubled)) == 1


def test_garbage_input_yields_nothing():
    assert parse_gpu_models("not lspci output at all") == ()
    assert parse_gpu_models("") == ()
