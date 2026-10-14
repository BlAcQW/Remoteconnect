"""Participant tracking for active sessions.

Tracks which clients are connected to each session and their roles.
The backend pushes participant_joined / participant_left events; the
agent mirrors them locally so participants_get returns a snapshot
without a round-trip to the backend.
"""
from __future__ import annotations

import time
from typing import Any

_participants: dict[str, dict[str, Any]] = {}  # id → participant record


def add(p: dict[str, Any]) -> None:
    pid = str(p.get("id", ""))
    if not pid:
        return
    if "connectedAt" not in p:
        p = {**p, "connectedAt": int(time.time() * 1000)}
    _participants[pid] = p


def remove(pid: str) -> None:
    _participants.pop(str(pid), None)


def list_all() -> list[dict[str, Any]]:
    return list(_participants.values())


def clear() -> None:
    _participants.clear()
