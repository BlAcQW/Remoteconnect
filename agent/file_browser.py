"""Filesystem browser for the technician panel.

Returns directory listings keyed by absolute path. On Windows an empty
or null path enumerates the fixed/removable drives instead — this is
the natural "go up to the top" behaviour customers expect.

Listings cap at LIST_CAP entries (default 5000) so a directory with
half a million files doesn't push a multi-megabyte payload through
the WS. The cap is per-call; technicians can still drill in.

Errors per-entry (e.g. PermissionError on a single child) are swallowed
so one inaccessible file doesn't black-hole the whole listing.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

LIST_CAP = 5000


def list_drives() -> list[dict[str, Any]]:
    """Enumerate Windows fixed and removable drives. Falls back to an
    empty list on non-Windows. Uses psutil because it handles drives
    that exist but aren't ready (empty optical, unmounted USB) without
    blowing up the listing."""
    if sys.platform != "win32":
        return []
    try:
        import psutil
    except ImportError:
        # Fallback: probe A..Z manually.
        out: list[dict[str, Any]] = []
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            root = Path(f"{letter}:\\")
            if root.exists():
                out.append({"name": f"{letter}:\\", "kind": "drive", "size": None, "mtime": None})
        return out

    out = []
    for part in psutil.disk_partitions(all=False):
        out.append({
            "name": part.mountpoint,
            "kind": "drive",
            "size": None,
            "mtime": None,
            "fstype": part.fstype,
        })
    return out


def _entry_for(p: Path) -> dict[str, Any] | None:
    """Build one listing entry. Returns None on any error so we can drop
    the offending row rather than aborting the whole listing."""
    try:
        st = p.lstat()
    except (OSError, ValueError):
        return None
    is_dir = p.is_dir()
    return {
        "name": p.name,
        "kind": "dir" if is_dir else "file",
        "size": None if is_dir else int(getattr(st, "st_size", 0)),
        "mtime": float(getattr(st, "st_mtime", 0)),
    }


def list_dir(raw_path: str | None) -> dict[str, Any]:
    """Return a dict suitable for the dir_list_response payload.

    Shape: {"path": <resolved or input>, "entries": [...], "error": str|None}
    """
    # Empty / null / "drives:" → top-level: drives on Windows, "/" elsewhere.
    if not raw_path or raw_path in ("drives:", "/", "\\"):
        if sys.platform == "win32":
            return {"path": "", "entries": list_drives(), "error": None}
        try:
            entries = _list_one(Path("/"))
        except Exception as e:
            return {"path": "/", "entries": [], "error": str(e)}
        return {"path": "/", "entries": entries, "error": None}

    try:
        target = Path(raw_path).resolve(strict=False)
    except (OSError, ValueError) as e:
        return {"path": raw_path, "entries": [], "error": f"invalid path: {e}"}

    if not target.exists():
        return {"path": str(target), "entries": [], "error": "not found"}
    if not target.is_dir():
        return {"path": str(target), "entries": [], "error": "not a directory"}

    try:
        entries = _list_one(target)
    except Exception as e:  # broad on purpose — any OS surprise lands here
        log.exception("list_dir failed for %s", target)
        return {"path": str(target), "entries": [], "error": str(e)}
    return {"path": str(target), "entries": entries, "error": None}


def _list_one(target: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with os.scandir(target) as it:
            for entry in it:
                row = _entry_for(Path(entry.path))
                if row is None:
                    continue
                rows.append(row)
                if len(rows) >= LIST_CAP:
                    break
    except PermissionError:
        return rows  # show whatever we got
    # Folders first, then files; alphabetical within each group.
    rows.sort(key=lambda r: (r["kind"] != "dir", r["name"].lower()))
    return rows
