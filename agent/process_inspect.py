"""Process inspection + kill, backed by psutil.

The agent only enumerates processes — it doesn't poll continuously.
Each `process_list` request walks the table once and returns a snapshot.
CPU% is delta-based so the first reading is misleading; we work around
that by pre-priming via `psutil.cpu_percent(None)` calls.

`psutil` is imported lazily (matching the rest of the agent) so a smoke
boot on a host without it lands a clean error rather than crashing at
import time.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

log = logging.getLogger(__name__)

# Cap returned rows so a 5 000-process desktop doesn't push a multi-MB
# JSON message through the WS. Sorted by descending RSS so the heaviest
# processes are kept.
LIST_CAP = 1000


def list_processes() -> list[dict[str, Any]]:
    """Enumerate processes. Returns one dict per process with the columns
    the technician panel needs (pid, name, cpu_pct, mem_mb, user, started_at).
    Errors on individual processes are swallowed — a "permission denied"
    on one row mustn't kill the whole listing."""
    import psutil

    self_pid = os.getpid()
    parent_pid = os.getppid()

    rows: list[dict[str, Any]] = []
    for proc in psutil.process_iter(attrs=("pid", "name", "username", "create_time")):
        try:
            info = proc.info
            with proc.oneshot():
                # cpu_percent without a prior interval call returns the
                # delta since the last query for this PID — first reading
                # is 0 which is misleading but acceptable for a snapshot.
                cpu = proc.cpu_percent(interval=None)
                mem = proc.memory_info().rss / (1024 * 1024)
            rows.append({
                "pid": info["pid"],
                "name": info.get("name") or "",
                "user": info.get("username") or "",
                "cpu_pct": round(float(cpu), 1),
                "mem_mb": round(float(mem), 1),
                "started_at": float(info.get("create_time") or 0),
                "is_agent": info["pid"] in (self_pid, parent_pid),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:
            log.exception("process row failed for pid=%s", getattr(proc, "pid", "?"))
            continue

    # Heaviest first — operator usually wants to spot a runaway, not the
    # alphabetical first entry.
    rows.sort(key=lambda r: r["mem_mb"], reverse=True)
    return rows[:LIST_CAP]


def kill(pid: int, force: bool = False, grace_s: float = 3.0) -> tuple[bool, str | None]:
    """Terminate `pid`. Returns (ok, error). Refuses to touch the agent's
    own PID or its parent (PyInstaller bootstrap). `force=True` skips
    SIGTERM and goes straight to SIGKILL / TerminateProcess."""
    import psutil

    self_pid = os.getpid()
    parent_pid = os.getppid()
    if pid in (self_pid, parent_pid):
        return False, "refusing to kill the agent process"

    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return False, "no such process"
    except Exception as e:
        return False, str(e)

    try:
        if force:
            proc.kill()
        else:
            proc.terminate()
            try:
                proc.wait(timeout=grace_s)
            except psutil.TimeoutExpired:
                # graceful term didn't take — escalate
                proc.kill()
        # confirm
        try:
            proc.wait(timeout=1.0)
        except psutil.TimeoutExpired:
            return False, "process did not exit"
        return True, None
    except psutil.AccessDenied:
        return False, "access denied"
    except psutil.NoSuchProcess:
        # raced with another exit — counts as success
        return True, None
    except Exception as e:
        return False, str(e)
