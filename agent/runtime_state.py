"""Mutable, agent-wide runtime state shared between the WS dispatch loop
and any subprocess publisher. Written from the agent (in response to
technician commands), read from the publisher every frame.

Persisted to a JSON file so a publisher launched as a *separate* process
can pick up changes without IPC. The publisher polls the file at frame-
boundary cadence — it's tiny so the read is cheap.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from . import config

log = logging.getLogger(__name__)

STATE_PATH: Path = config.SHARED_DIR.parent / ".runtime_state.json"
_lock = threading.Lock()


DEFAULT_STATE: dict[str, Any] = {
    "monitor_index": 1,
    "fps": 15,
    "width": 1280,
    "height": 720,
    "quality": "high",     # high | medium | low | grayscale
    "input_locked": False,
    "screen_locked": False,
    "updated_at": 0,
}


def load() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return dict(DEFAULT_STATE)
    try:
        with _lock:
            data = json.loads(STATE_PATH.read_text())
        # backfill any missing keys (forward-compatible)
        merged = dict(DEFAULT_STATE)
        merged.update(data or {})
        return merged
    except Exception as e:
        log.warning("runtime_state load failed (%s); resetting", e)
        return dict(DEFAULT_STATE)


def update(**kw: Any) -> dict[str, Any]:
    with _lock:
        cur = load()
        cur.update(kw)
        cur["updated_at"] = int(time.time())
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = STATE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(cur))
            os.replace(tmp, STATE_PATH)
        except Exception as e:
            log.warning("runtime_state write failed: %s", e)
        return cur
