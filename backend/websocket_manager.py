"""WebSocket connection registries.

`active_connections` maps machine_id → agent WS (one per registered machine).
`technician_connections` maps session_id → SET of technician browser WS so
multiple technicians can join the same session and an agent's responses
get fanned out to all of them.

`guest_connections` maps token → WS for read-only guest viewers.
"""
from __future__ import annotations

import json
import logging
from typing import Dict, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: Dict[str, WebSocket] = {}
        self.technician_connections: Dict[str, Set[WebSocket]] = {}
        self.guest_connections: Dict[str, WebSocket] = {}

    # ── Agent side ──────────────────────────────────────────────────────────
    async def connect(self, machine_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections[machine_id] = websocket
        logger.info(
            "Agent %s connected. agents=%d sessions_w_techs=%d guests=%d",
            machine_id,
            len(self.active_connections),
            len(self.technician_connections),
            len(self.guest_connections),
        )

    async def disconnect(self, machine_id: str) -> None:
        if machine_id in self.active_connections:
            del self.active_connections[machine_id]
            logger.info("Agent %s disconnected. agents=%d", machine_id, len(self.active_connections))

    async def send_to_machine(self, machine_id: str, message: dict) -> None:
        ws = self.active_connections.get(machine_id)
        if ws is None:
            logger.warning("Agent %s not connected; dropping message type=%s", machine_id, message.get("type"))
            return
        try:
            await ws.send_text(json.dumps(message))
        except Exception as e:
            logger.error("Failed to send to agent %s: %s", machine_id, e)
            await self.disconnect(machine_id)

    async def broadcast(self, message: dict) -> None:
        disconnected = []
        for machine_id, ws in self.active_connections.items():
            try:
                await ws.send_text(json.dumps(message))
            except Exception as e:
                logger.error("broadcast → %s failed: %s", machine_id, e)
                disconnected.append(machine_id)
        for machine_id in disconnected:
            await self.disconnect(machine_id)

    def get_connected_machines(self) -> list[str]:
        return list(self.active_connections.keys())

    # ── Technician side ─────────────────────────────────────────────────────
    async def connect_technician(self, session_id: str, websocket: WebSocket) -> None:
        self.technician_connections.setdefault(session_id, set()).add(websocket)
        logger.info(
            "Technician opened session %s. techs_in_session=%d",
            session_id,
            len(self.technician_connections[session_id]),
        )

    async def disconnect_technician(self, session_id: str, websocket: WebSocket) -> None:
        peers = self.technician_connections.get(session_id)
        if peers is None:
            return
        peers.discard(websocket)
        if not peers:
            del self.technician_connections[session_id]
        logger.info(
            "Technician closed session %s. remaining_in_session=%d",
            session_id,
            0 if peers is None else len(peers),
        )

    async def send_to_technician(self, session_id: str, message: dict) -> int:
        """Broadcast to all technicians in a session. Returns count delivered."""
        peers = self.technician_connections.get(session_id)
        if not peers:
            return 0
        payload = json.dumps(message)
        delivered = 0
        broken: list[WebSocket] = []
        for ws in list(peers):
            try:
                await ws.send_text(payload)
                delivered += 1
            except Exception as e:
                logger.warning("send_to_technician failed (session=%s): %s", session_id, e)
                broken.append(ws)
        for ws in broken:
            peers.discard(ws)
        return delivered

    async def send_bytes_to_technician(self, session_id: str, data: bytes) -> int:
        """Fan out binary frames (e.g. MJPEG video) to technicians in a session.

        Separate from send_to_technician() because video frames are hot path —
        we skip JSON encoding, share the same bytes object across all peers.
        """
        peers = self.technician_connections.get(session_id)
        if not peers:
            return 0
        delivered = 0
        broken: list[WebSocket] = []
        for ws in list(peers):
            try:
                await ws.send_bytes(data)
                delivered += 1
            except Exception as e:
                logger.warning("send_bytes_to_technician failed (session=%s): %s", session_id, e)
                broken.append(ws)
        for ws in broken:
            peers.discard(ws)
        return delivered

    def technician_count(self, session_id: str) -> int:
        return len(self.technician_connections.get(session_id, ()))

    # ── Guest side ──────────────────────────────────────────────────────────
    async def connect_guest(self, token: str, websocket: WebSocket) -> None:
        existing = self.guest_connections.get(token)
        if existing is not None and existing is not websocket:
            try:
                await existing.close(code=1000)
            except Exception:
                pass
        self.guest_connections[token] = websocket

    async def disconnect_guest(self, token: str, websocket: WebSocket) -> None:
        if self.guest_connections.get(token) is websocket:
            del self.guest_connections[token]

    async def send_to_guest(self, token: str, message: dict) -> bool:
        ws = self.guest_connections.get(token)
        if ws is None:
            return False
        try:
            await ws.send_text(json.dumps(message))
            return True
        except Exception:
            self.guest_connections.pop(token, None)
            return False


manager = ConnectionManager()
