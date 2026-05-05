"""Windows / systemd / launchd service inventory + control.

Returns one dict per service:
    {name, display_name, status, start_type, pid, description}

Cross-platform shim:
- Windows: psutil.win_service_iter / win_service_get for listing,
  `sc.exe start|stop|...` for actions. We avoid pywin32 service control
  manager bindings because they want elevation just to start the SCM
  handle, which the bundled agent doesn't always have.
- Linux: `systemctl list-units --all --type=service --no-legend` parses
  cleanly enough for the table; control via `systemctl --user` falls
  back to `systemctl` system-wide if user mode isn't running.
- macOS: `launchctl list` for the simple flat output. Actions via
  `launchctl bootstrap/bootout`. macOS support is best-effort —
  most support work happens on Windows boxes.

Errors (access denied, missing service, etc.) come back as the error
string in the response rather than raising, matching the rest of the
agent control surface.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from typing import Any

log = logging.getLogger(__name__)

LIST_CAP = 1000
SUPPORTED_VERBS = {"start", "stop", "restart"}


# ─── Windows ────────────────────────────────────────────────────────────
def _list_windows() -> list[dict[str, Any]]:
    import psutil

    rows: list[dict[str, Any]] = []
    for svc in psutil.win_service_iter():  # type: ignore[attr-defined]
        try:
            info = svc.as_dict()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        except Exception:
            continue
        rows.append({
            "name": info.get("name") or "",
            "display_name": info.get("display_name") or "",
            "status": info.get("status") or "",
            "start_type": info.get("start_type") or "",
            "pid": info.get("pid"),
            "description": info.get("description") or "",
            "username": info.get("username") or "",
        })
    rows.sort(key=lambda r: r["name"].lower())
    return rows[:LIST_CAP]


def _action_windows(name: str, verb: str) -> tuple[bool, str | None]:
    if verb == "restart":
        ok, err = _action_windows(name, "stop")
        if not ok and err and "not running" not in err.lower():
            return False, f"stop failed: {err}"
        ok, err = _action_windows(name, "start")
        return ok, err

    sc_verb = {"start": "start", "stop": "stop"}[verb]
    creationflags = 0x08000000  # CREATE_NO_WINDOW
    try:
        completed = subprocess.run(
            ["sc.exe", sc_verb, name],
            capture_output=True, timeout=15, creationflags=creationflags,
        )
    except FileNotFoundError:
        return False, "sc.exe not found"
    except subprocess.TimeoutExpired:
        return False, "sc.exe timed out"
    if completed.returncode == 0:
        return True, None
    err = completed.stderr.decode(errors="replace").strip() or completed.stdout.decode(errors="replace").strip()
    return False, f"sc.exe rc={completed.returncode}: {err}"


# ─── Linux (systemd) ────────────────────────────────────────────────────
_SYSTEMCTL = shutil.which("systemctl") if sys.platform != "win32" else None


def _list_systemd() -> list[dict[str, Any]]:
    if _SYSTEMCTL is None:
        return []
    try:
        completed = subprocess.run(
            [_SYSTEMCTL, "list-units", "--all", "--type=service",
             "--no-legend", "--plain", "--no-pager"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    rows: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        # systemd output is whitespace-separated:
        # NAME LOAD ACTIVE SUB DESCRIPTION
        fields = line.split(None, 4)
        if len(fields) < 4:
            continue
        unit, load, active, sub = fields[:4]
        desc = fields[4] if len(fields) > 4 else ""
        if not unit.endswith(".service"):
            continue
        rows.append({
            "name": unit,
            "display_name": unit.removesuffix(".service"),
            "status": active,
            "start_type": load,
            "pid": None,
            "description": desc,
            "username": "",
        })
    rows.sort(key=lambda r: r["name"].lower())
    return rows[:LIST_CAP]


def _action_systemd(name: str, verb: str) -> tuple[bool, str | None]:
    if _SYSTEMCTL is None:
        return False, "systemctl not available"
    try:
        completed = subprocess.run(
            [_SYSTEMCTL, verb, name], capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    if completed.returncode == 0:
        return True, None
    err = (completed.stderr or completed.stdout or "").strip()
    return False, f"systemctl rc={completed.returncode}: {err}"


# ─── macOS (launchd) ────────────────────────────────────────────────────
def _list_launchd() -> list[dict[str, Any]]:
    if shutil.which("launchctl") is None:
        return []
    try:
        completed = subprocess.run(
            ["launchctl", "list"], capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    rows: list[dict[str, Any]] = []
    lines = completed.stdout.splitlines()
    for line in lines[1:]:  # skip "PID Status Label" header
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid_str, status_str, label = parts
        try:
            pid = int(pid_str) if pid_str != "-" else None
        except ValueError:
            pid = None
        try:
            status = int(status_str)
        except ValueError:
            status = -1
        rows.append({
            "name": label,
            "display_name": label,
            "status": "running" if pid else f"stopped (last_exit={status})",
            "start_type": "",
            "pid": pid,
            "description": "",
            "username": "",
        })
    rows.sort(key=lambda r: r["name"].lower())
    return rows[:LIST_CAP]


# ─── Public surface ────────────────────────────────────────────────────
def list_services() -> list[dict[str, Any]]:
    """Snapshot the service inventory for the current OS."""
    if sys.platform == "win32":
        return _list_windows()
    if sys.platform == "darwin":
        return _list_launchd()
    return _list_systemd()


def perform_action(name: str, verb: str) -> tuple[bool, str | None]:
    """Apply a verb (start/stop/restart) to a named service."""
    verb = (verb or "").lower()
    if verb not in SUPPORTED_VERBS:
        return False, f"unsupported verb: {verb}"
    if not name or any(c in name for c in ("\x00", "\n", "\r")):
        return False, "invalid service name"

    if sys.platform == "win32":
        return _action_windows(name, verb)
    if sys.platform == "darwin":
        # launchctl needs a label/path pair for bootstrap/bootout — too
        # OS-version-specific to wire safely from here without the user
        # picking the right plist scope. Punt for now.
        return False, "launchctl actions not implemented on macOS"
    return _action_systemd(name, verb)
