"""Daily.co REST client used by the sessions router.

When ``DAILY_API_KEY`` is unset (dev mode) the client transparently falls
back to mock URLs/tokens so the rest of the system can be exercised
without an upstream dependency.

Reference: https://docs.daily.co/reference
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional, TypedDict

import httpx

log = logging.getLogger(__name__)

DAILY_API_BASE = "https://api.daily.co/v1"
ROOM_TTL_SECONDS = 60 * 60  # PRD: 1 hour expiry
HTTP_TIMEOUT = 10.0


class Room(TypedDict):
    name: str
    url: str


def _api_key() -> Optional[str]:
    key = os.getenv("DAILY_API_KEY")
    return key or None


def is_enabled() -> bool:
    return _api_key() is not None


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_api_key()}"}


def _mock_room(session_id: str) -> Room:
    name = f"session-{session_id}"
    # Match the real Daily URL shape (https://<team>.daily.co/<name>) so the
    # last path segment is the room name in both modes.
    return Room(name=name, url=f"https://mock-daily.co/{name}")


async def create_room(session_id: str) -> Room:
    """Create a Daily room for ``session_id``. Returns mock data if no key."""
    if not is_enabled():
        log.info("DAILY_API_KEY not set — returning mock room for %s", session_id)
        return _mock_room(session_id)

    payload = {
        "name": f"session-{session_id}",
        "properties": {
            "max_participants": 2,
            "enable_screenshare": True,
            "exp": int(time.time()) + ROOM_TTL_SECONDS,
        },
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.post(
            f"{DAILY_API_BASE}/rooms", headers=_auth_headers(), json=payload
        )
    if r.status_code >= 400:
        log.error("Daily create_room failed: %s %s", r.status_code, r.text[:300])
        r.raise_for_status()
    body = r.json()
    return Room(name=body["name"], url=body["url"])


async def delete_room(name: str) -> bool:
    """Delete a Daily room by name. No-op (returns True) when disabled."""
    if not is_enabled():
        log.info("DAILY_API_KEY not set — skipping room delete for %s", name)
        return True

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.delete(f"{DAILY_API_BASE}/rooms/{name}", headers=_auth_headers())
    if r.status_code in (200, 204, 404):
        return True
    log.warning("Daily delete_room %s -> %s %s", name, r.status_code, r.text[:200])
    return False


async def create_meeting_token(
    room_name: str,
    user_name: str,
    is_owner: bool = False,
    ttl_seconds: int = ROOM_TTL_SECONDS,
) -> Optional[str]:
    """Issue a meeting token scoped to a room. Returns None if disabled."""
    if not is_enabled():
        return None

    payload = {
        "properties": {
            "room_name": room_name,
            "user_name": user_name,
            "is_owner": is_owner,
            "exp": int(time.time()) + ttl_seconds,
        }
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.post(
            f"{DAILY_API_BASE}/meeting-tokens", headers=_auth_headers(), json=payload
        )
    if r.status_code >= 400:
        log.error("Daily create_meeting_token failed: %s %s", r.status_code, r.text[:300])
        r.raise_for_status()
    return r.json().get("token")
