"""Readable details about the machine Ignis is running on.

The parsers are pure so they can be tested without a Linux host. /proc is
mounted inside the Flatpak sandbox and describes the real hardware, but the
GPU model and the host OS name need commands run on the host.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from ignis.core.host import HostBridge

log = logging.getLogger(__name__)

#: PCI classes that identify a graphics device in lspci output.
GPU_CLASSES = (
    "vga compatible controller",
    "3d controller",
    "display controller",
)

_LSPCI_LINE = re.compile(r"^\S+\s+(?P<cls>[^:]+):\s*(?P<name>.+)$")
_REVISION = re.compile(r"\s*\(rev [^)]*\)\s*$")
_BRACKETED = re.compile(r"\[([^\[\]]+)\]")


@dataclass(frozen=True)
class SystemInfo:
    """What Ignis can tell the user about their machine."""

    graphics: tuple[str, ...] = ()
    processor: str = ""
    memory: str = ""
    operating_system: str = ""

    @property
    def graphics_summary(self) -> str:
        """All GPUs on one line."""
        return " · ".join(self.graphics)


def parse_cpu_model(cpuinfo: str) -> str:
    """Extract the CPU model name from /proc/cpuinfo."""
    for line in cpuinfo.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        # x86 uses "model name"; ARM boards use "Model" or "Hardware".
        if key.strip().lower() in ("model name", "hardware", "model"):
            model = value.strip()
            if model:
                return model
    return ""


def parse_memory_total(meminfo: str) -> str:
    """Total RAM from /proc/meminfo, rounded for display."""
    for line in meminfo.splitlines():
        if not line.startswith("MemTotal:"):
            continue
        parts = line.split()
        if len(parts) < 2:
            return ""
        try:
            kilobytes = int(parts[1])
        except ValueError:
            return ""
        return f"{kilobytes / 1024 / 1024:.0f} GB"
    return ""


def parse_os_name(os_release: str) -> str:
    """PRETTY_NAME from an os-release file."""
    for line in os_release.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "PRETTY_NAME":
            return value.strip().strip('"').strip("'")
    return ""


def parse_gpu_models(lspci_output: str) -> tuple[str, ...]:
    """Marketing names of the graphics devices in `lspci` output.

    Prefers the last bracketed group, which is where all three vendors put
    the name people recognise: "... [AMD/ATI] Navi 32 [Radeon RX 7800 XT]"
    -> "Radeon RX 7800 XT".
    """
    models: list[str] = []
    for line in lspci_output.splitlines():
        match = _LSPCI_LINE.match(line.strip())
        if match is None:
            continue
        if match["cls"].strip().lower() not in GPU_CLASSES:
            continue

        name = _REVISION.sub("", match["name"]).strip()
        brackets = _BRACKETED.findall(name)
        model = brackets[-1].strip() if brackets else name
        if model and model not in models:
            models.append(model)
    return tuple(models)


def gather(bridge: HostBridge, vendors: frozenset[str] = frozenset()) -> SystemInfo:
    """Collect system details. Never raises — missing pieces come back empty."""
    return SystemInfo(
        graphics=_graphics(bridge, vendors),
        processor=parse_cpu_model(_read("/proc/cpuinfo")),
        memory=parse_memory_total(_read("/proc/meminfo")),
        operating_system=_host_os_name(bridge),
    )


def _graphics(bridge: HostBridge, vendors: frozenset[str]) -> tuple[str, ...]:
    """GPU names via lspci, falling back to the vendors found in sysfs."""
    result = bridge.run(["lspci"], timeout=20, check=False)
    if result.ok:
        models = parse_gpu_models(result.output)
        if models:
            return models
        log.info("lspci reported no graphics devices")
    else:
        log.info("lspci unavailable (exit %d) — falling back to sysfs vendors",
                 result.returncode)

    from ignis.core import hardware

    return tuple(hardware.label(v) for v in sorted(vendors))


def _host_os_name(bridge: HostBridge) -> str:
    """The host's OS name.

    Read through the bridge on purpose: /etc/os-release inside the sandbox
    describes the GNOME runtime, not Bazzite.
    """
    result = bridge.run(["cat", "/etc/os-release"], timeout=20, check=False)
    return parse_os_name(result.output) if result.ok else ""


def _read(path: str) -> str:
    """Read a /proc file, returning "" if it isn't available."""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        log.info("could not read %s", path, exc_info=True)
        return ""
