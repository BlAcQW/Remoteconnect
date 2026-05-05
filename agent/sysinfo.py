"""System / device report.

One-shot snapshot of CPU, RAM, disks, OS, network adapters, and a few
per-platform extras (Windows BIOS / serial via WMI when available). The
technician panel renders this as a single read-only summary — first
thing every support session opens to "what am I dealing with."

Lazy imports throughout so a smoke boot on a host without psutil
doesn't break the agent. Errors per-section are swallowed and reported
inline rather than raising, so one failed lookup doesn't poison the
whole report.
"""
from __future__ import annotations

import logging
import os
import platform
import socket
import sys
import time
from typing import Any

log = logging.getLogger(__name__)


def _safe(label: str, fn) -> tuple[Any, str | None]:
    """Call `fn` and return (value, error). Errors are stringified so the
    panel can show "BIOS: <error reading WMI>" instead of an empty cell."""
    try:
        return fn(), None
    except Exception as e:  # broad on purpose — diagnostics must never fail
        log.warning("sysinfo.%s failed: %s", label, e)
        return None, f"{type(e).__name__}: {e}"


def _cpu_info() -> dict[str, Any]:
    import psutil

    freq = psutil.cpu_freq()
    return {
        "logical_cores": psutil.cpu_count(logical=True),
        "physical_cores": psutil.cpu_count(logical=False),
        "frequency_mhz": round(float(freq.current), 0) if freq else None,
        "max_frequency_mhz": round(float(freq.max), 0) if freq and freq.max else None,
        "model": platform.processor() or platform.machine(),
        "load_pct": round(float(psutil.cpu_percent(interval=0.2)), 1),
    }


def _memory_info() -> dict[str, Any]:
    import psutil

    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    return {
        "total_mb": round(vm.total / (1024 * 1024)),
        "available_mb": round(vm.available / (1024 * 1024)),
        "used_pct": round(float(vm.percent), 1),
        "swap_total_mb": round(sw.total / (1024 * 1024)),
        "swap_used_pct": round(float(sw.percent), 1),
    }


def _disk_info() -> list[dict[str, Any]]:
    import psutil

    out = []
    for part in psutil.disk_partitions(all=False):
        # Skip pseudo-fs that show up on Linux (snap, squashfs, etc.)
        if not part.fstype or part.fstype in {"squashfs", "tmpfs", "devtmpfs"}:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        out.append({
            "mount": part.mountpoint,
            "device": part.device,
            "fstype": part.fstype,
            "total_gb": round(usage.total / (1024 ** 3), 1),
            "used_gb": round(usage.used / (1024 ** 3), 1),
            "used_pct": round(float(usage.percent), 1),
        })
    return out


def _network_info() -> list[dict[str, Any]]:
    import psutil

    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    out = []
    for iface, items in addrs.items():
        # Skip loopback / inactive — clutter the report otherwise.
        if iface in {"lo", "Loopback Pseudo-Interface 1"}:
            continue
        st = stats.get(iface)
        if st and not st.isup:
            continue
        ipv4 = []
        ipv6 = []
        mac = None
        for a in items:
            fam_name = getattr(a.family, "name", str(a.family))
            if fam_name == "AF_INET":
                ipv4.append(a.address)
            elif fam_name == "AF_INET6":
                # Strip IPv6 zone-id suffix for display (eth0%2 → eth0)
                addr = a.address.split("%", 1)[0]
                ipv6.append(addr)
            elif fam_name in {"AF_LINK", "AF_PACKET"}:
                mac = a.address
        out.append({
            "name": iface,
            "mac": mac,
            "ipv4": ipv4,
            "ipv6": ipv6,
            "speed_mbps": int(st.speed) if st and st.speed else None,
        })
    return out


def _os_info() -> dict[str, Any]:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "hostname": socket.gethostname(),
        "python": sys.version.split()[0],
        "uptime_s": int(time.time() - _boot_time()),
    }


def _boot_time() -> float:
    try:
        import psutil

        return float(psutil.boot_time())
    except Exception:
        return time.time()


def _windows_extras() -> dict[str, Any]:
    """BIOS / serial number / OEM info via the registry. We deliberately
    avoid pywin32 (extra dependency, heavy DLLs) — the registry path is
    enough for the fields we surface."""
    import winreg  # type: ignore[import-not-found]

    out: dict[str, Any] = {}
    bios_keys = [
        ("HARDWARE\\DESCRIPTION\\System\\BIOS", "BIOSVendor", "bios_vendor"),
        ("HARDWARE\\DESCRIPTION\\System\\BIOS", "BIOSVersion", "bios_version"),
        ("HARDWARE\\DESCRIPTION\\System\\BIOS", "SystemManufacturer", "manufacturer"),
        ("HARDWARE\\DESCRIPTION\\System\\BIOS", "SystemProductName", "product_name"),
        ("HARDWARE\\DESCRIPTION\\System\\BIOS", "SystemSKU", "sku"),
        # Serial number isn't always populated; we report whatever's there.
        ("HARDWARE\\DESCRIPTION\\System\\BIOS", "SystemSerialNumber", "serial"),
    ]
    for subkey, value_name, label in bios_keys:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey) as k:
                val, _ = winreg.QueryValueEx(k, value_name)
                out[label] = str(val)
        except (FileNotFoundError, OSError):
            continue

    # Windows edition + display version (24H2 etc.)
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
        ) as k:
            for value_name, label in (
                ("ProductName", "edition"),
                ("DisplayVersion", "display_version"),
                ("CurrentBuild", "build"),
                ("UBR", "ubr"),
            ):
                try:
                    val, _ = winreg.QueryValueEx(k, value_name)
                    out[label] = str(val)
                except (FileNotFoundError, OSError):
                    continue
    except OSError:
        pass

    return out


def collect() -> dict[str, Any]:
    """Top-level entry point. Returns a JSON-serializable dict; per-section
    errors land in the `errors` field rather than raising."""
    errors: dict[str, str] = {}
    cpu, err = _safe("cpu", _cpu_info)
    if err:
        errors["cpu"] = err
    mem, err = _safe("memory", _memory_info)
    if err:
        errors["memory"] = err
    disks, err = _safe("disks", _disk_info)
    if err:
        errors["disks"] = err
    nets, err = _safe("network", _network_info)
    if err:
        errors["network"] = err
    os_info, err = _safe("os", _os_info)
    if err:
        errors["os"] = err

    extras: dict[str, Any] = {}
    if sys.platform == "win32":
        ext, err = _safe("windows_extras", _windows_extras)
        if ext:
            extras = ext
        if err:
            errors["windows_extras"] = err

    return {
        "captured_at": time.time(),
        "agent": {
            "pid": os.getpid(),
            "executable": sys.executable,
        },
        "cpu": cpu,
        "memory": mem,
        "disks": disks or [],
        "network": nets or [],
        "os": os_info,
        "extras": extras,
        "errors": errors,
    }
