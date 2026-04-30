import asyncio
import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..database import get_db
from ..models.machine import Machine
from ..models.session import Session
from ..models.user import User
from ..models.file_transfer import FileTransfer
from ..websocket_manager import manager

logger = logging.getLogger(__name__)
router = APIRouter()

JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = "HS256"
TECHNICIAN_COOKIE_NAME = "rc_jwt"
GUEST_AUDIENCE = "rc-guest"

IDLE_TIMEOUT_S = int(os.getenv("TECH_WS_IDLE_TIMEOUT_S", "300"))  # 5 min default

# tech → agent allowlist (input passthrough + file transfer + Phase 7 commands)
TECH_TO_AGENT: frozenset[str] = frozenset(
    {
        # input
        "mouse_move", "mouse_click", "mouse_scroll",
        "key_press", "type_text",
        # files
        "file_upload_start", "file_upload_cancel", "file_chunk", "file_download_request",
        # phase-7 commands
        "monitor_select", "fps_change", "quality_change",
        "clipboard_get", "clipboard_set",
        "cad_send", "lock_screen", "unlock_screen",
        "input_lock", "input_unlock",
        "wake_lan",
    }
)

# agent → tech allowlist (file transfer responses + phase-7 events)
AGENT_TO_TECH: frozenset[str] = frozenset(
    {
        "file_upload_ack", "file_upload_complete",
        "file_chunk", "file_download_complete", "file_download_error",
        "monitor_list", "clipboard_data",
        "consent_required", "consent_granted", "consent_denied",
        "wake_sent", "wake_failed",
    }
)

# tech → tech (broadcast within a session) — chat + collaborative annotation
TECH_TO_TECH: frozenset[str] = frozenset({"chat", "annotation_draw", "annotation_clear"})

MAX_TRANSFER_BYTES = 100 * 1024 * 1024


# Binary frame envelope from agent → backend (MJPEG video):
#   [u8 type=1][u8 sid_len][6 reserved bytes][session_id utf-8][JPEG bytes]
# type=1   → JPEG frame (only type defined for now)
# Backend strips the header and forwards just the JPEG to the technician(s)
# in that session. Technician WS is already session-scoped so no header is
# needed downstream.
FRAME_HEADER_LEN = 8
FRAME_TYPE_JPEG = 1


@router.websocket("/agent/{machine_id}")
async def agent_ws(
    websocket: WebSocket,
    machine_id: str,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(select(Machine).where(Machine.id == machine_id))
    machine = result.scalar_one_or_none()
    if not machine or machine.token != token:
        await websocket.close(code=1008)
        return

    await manager.connect(machine_id, websocket)
    try:
        while True:
            event = await websocket.receive()
            etype = event.get("type")
            if etype == "websocket.disconnect":
                raise WebSocketDisconnect(code=event.get("code", 1000))

            # ── Binary path: MJPEG video frames ─────────────────────────────
            if "bytes" in event and event["bytes"] is not None:
                data: bytes = event["bytes"]
                if len(data) < FRAME_HEADER_LEN:
                    logger.warning("Agent %s sent short binary frame (%d bytes)", machine_id, len(data))
                    continue
                ftype = data[0]
                sid_len = data[1]
                payload_start = FRAME_HEADER_LEN + sid_len
                if ftype != FRAME_TYPE_JPEG or payload_start > len(data):
                    logger.warning(
                        "Agent %s sent unknown binary frame type=%d sid_len=%d total=%d",
                        machine_id, ftype, sid_len, len(data),
                    )
                    continue
                try:
                    session_id = data[FRAME_HEADER_LEN:payload_start].decode("ascii")
                except UnicodeDecodeError:
                    logger.warning("Agent %s sent frame with non-ascii session_id", machine_id)
                    continue
                # Forward only the JPEG body. Slice is a view, no copy.
                await manager.send_bytes_to_technician(session_id, data[payload_start:])
                continue

            # ── Text path: JSON control messages ────────────────────────────
            raw = event.get("text")
            if raw is None:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Agent %s sent non-JSON frame", machine_id)
                continue

            t = msg.get("type")
            session_id = msg.get("session_id")

            if t in AGENT_TO_TECH and session_id:
                delivered = await manager.send_to_technician(session_id, msg)

                # Forward audit-worthy outcomes
                if t == "consent_granted":
                    await update_session_status(db, session_id, "active")
                    await audit(db, "session.consent.granted", session_id=session_id, machine_id=machine_id)
                elif t == "consent_denied":
                    await update_session_status(db, session_id, "ended")
                    await audit(db, "session.consent.denied", session_id=session_id, machine_id=machine_id)
                elif t == "wake_sent":
                    await audit(db, "wake.sent", machine_id=machine_id, detail={"target": msg.get("mac")})
                elif t == "wake_failed":
                    await audit(db, "wake.failed", machine_id=machine_id, detail={"error": str(msg.get("reason"))})
                elif t.startswith("file_"):
                    await persist_file_transfer(db, session_id, msg)

                # Also fan-out file_chunk download to guest viewers (read-only watchers)
                if t == "file_chunk" and msg.get("session_id"):
                    pass  # guests don't get file chunks; explicit
                if delivered == 0 and t != "file_chunk":
                    logger.debug("agent msg type=%s session=%s had no tech to deliver to", t, session_id)
            else:
                logger.debug("Agent %s msg type=%s session=%s (not forwarded)", machine_id, t, session_id)

    except WebSocketDisconnect:
        logger.info("Agent %s WS disconnected", machine_id)
    finally:
        await manager.disconnect(machine_id)


async def update_session_status(db: AsyncSession, session_id: str, status: str) -> None:
    try:
        await db.execute(update(Session).where(Session.id == session_id).values(status=status))
        await db.commit()
    except Exception as e:
        logger.warning("update_session_status %s -> %s failed: %s", session_id, status, e)
        await db.rollback()


async def persist_file_transfer(db: AsyncSession, session_id: Optional[str], msg: dict) -> None:
    """Best-effort write a FileTransfer row from agent ack/complete events."""
    if not session_id:
        return
    t = msg.get("type")
    filename = msg.get("filename")
    if not filename:
        return
    try:
        if t == "file_upload_complete":
            db.add(FileTransfer(
                session_id=session_id,
                filename=str(filename),
                direction="upload",
                size_bytes=int(msg.get("size_bytes") or 0),
                status="ok",
            ))
            await db.commit()
        elif t == "file_upload_ack" and msg.get("status") == "rejected":
            db.add(FileTransfer(
                session_id=session_id,
                filename=str(filename),
                direction="upload",
                size_bytes=0,
                status="rejected",
            ))
            await db.commit()
        elif t == "file_download_complete":
            db.add(FileTransfer(
                session_id=session_id,
                filename=str(filename),
                direction="download",
                size_bytes=int(msg.get("size_bytes") or 0),
                status="ok",
            ))
            await db.commit()
        elif t == "file_download_error":
            db.add(FileTransfer(
                session_id=session_id,
                filename=str(filename),
                direction="download",
                size_bytes=0,
                status="error",
            ))
            await db.commit()
    except Exception as e:
        logger.warning("persist_file_transfer failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass


async def _user_from_cookie(websocket: WebSocket, db: AsyncSession) -> Optional[User]:
    raw = websocket.cookies.get(TECHNICIAN_COOKIE_NAME)
    if not raw or not JWT_SECRET:
        return None
    try:
        payload = jwt.decode(raw, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
    email = payload.get("sub")
    if not email:
        return None
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


@router.websocket("/technician/{session_id}")
async def technician_ws(
    websocket: WebSocket,
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    user = await _user_from_cookie(websocket, db)
    if user is None:
        await websocket.close(code=1008)
        return

    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if session is None:
        await websocket.close(code=1008)
        return
    if session.technician_id != user.id and user.role != "admin":
        await websocket.close(code=1008)
        return
    if session.status == "ended":
        await websocket.close(code=1008)
        return

    await websocket.accept()
    await manager.connect_technician(session_id, websocket)
    logger.info(
        "Technician %s opened session %s (machine=%s)",
        user.email, session_id, session.machine_id,
    )

    # Send a peer count so the UI can show "you and 1 other tech"
    peer_count = manager.technician_count(session_id)
    await websocket.send_json({
        "type": "peers",
        "count": peer_count,
    })
    if peer_count > 1:
        await manager.send_to_technician(session_id, {"type": "peers", "count": peer_count})

    try:
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=IDLE_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                logger.info(
                    "Technician %s idle on session %s for %ds — closing",
                    user.email, session_id, IDLE_TIMEOUT_S,
                )
                await audit(db, "session.idle_timeout", user_id=user.id, session_id=session_id)
                try:
                    await websocket.send_json({"type": "session_idle", "reason": "no input"})
                except Exception:
                    pass
                await websocket.close(code=1000)
                return

            t = data.get("type")
            if t in TECH_TO_AGENT:
                if t == "file_upload_start":
                    size = int(data.get("size_bytes", 0) or 0)
                    if size > MAX_TRANSFER_BYTES:
                        await websocket.send_json({
                            "type": "file_upload_ack",
                            "filename": data.get("filename"),
                            "status": "rejected",
                            "reason": f"file too large ({size} > {MAX_TRANSFER_BYTES} bytes)",
                        })
                        continue
                data["session_id"] = session_id
                await manager.send_to_machine(session.machine_id, data)
            elif t in TECH_TO_TECH:
                # Fan out to other technicians in the same session
                data["session_id"] = session_id
                data["from_user"] = user.email
                # Reflect to all (including sender so chat scrolls reliably)
                await manager.send_to_technician(session_id, data)
            else:
                logger.debug("Dropping type=%r from technician %s", t, user.email)
    except WebSocketDisconnect:
        logger.info("Technician %s closed session %s", user.email, session_id)
    except Exception:
        logger.exception("Error on technician channel for session %s", session_id)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        await manager.disconnect_technician(session_id, websocket)
        # Update remaining peer count
        remaining = manager.technician_count(session_id)
        if remaining > 0:
            await manager.send_to_technician(session_id, {"type": "peers", "count": remaining})


@router.websocket("/guest/{token}")
async def guest_ws(
    websocket: WebSocket,
    token: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Read-only guest channel. Token is a short-lived JWT scoped to a session_id."""
    if not JWT_SECRET:
        await websocket.close(code=1008)
        return
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM], audience=GUEST_AUDIENCE)
    except JWTError:
        await websocket.close(code=1008)
        return
    session_id = payload.get("sub")
    if not session_id:
        await websocket.close(code=1008)
        return
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if session is None or session.status == "ended":
        await websocket.close(code=1008)
        return

    await websocket.accept()
    await manager.connect_guest(token, websocket)
    await audit(db, "guest.invite.consumed", session_id=session_id, detail={"token_prefix": token[:8]})
    try:
        while True:
            # Guests are read-only; we just ignore inbound frames but keep the socket alive.
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=IDLE_TIMEOUT_S)
            except asyncio.TimeoutError:
                await websocket.close(code=1000)
                return
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect_guest(token, websocket)
