"""RemoteConnect client agent.

Lifecycle:
    1. On first run, register with the backend and persist credentials to
       config.json. On subsequent runs, reuse them.
    2. Run two concurrent tasks:
         - heartbeat_loop: HTTP PATCH /machines/{id}/heartbeat every N seconds
         - ws_loop: stay connected to /ws/agent/{id} with exponential-backoff
                    reconnect, dispatching commands as they arrive.
    3. On `start_session`, launch an in-process MJPEG streamer that captures
       the desktop with mss and pushes binary frames over the existing WS.
       Default video transport. The legacy Daily.co publisher subprocess is
       still supported when the backend tells us video_backend="daily".
"""
import asyncio
import json
import logging
import os
import signal
import struct
import sys
from typing import Any, Optional

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from . import config, control, runtime_state
from .input_handler import click_mouse, move_mouse, press_key, scroll_mouse, type_text
from .screen_capture import capture_frame, list_monitors
from .transfer_handlers import TransferDispatcher

log = logging.getLogger("agent")
_transfers = TransferDispatcher()

# Daily.co publisher subprocesses (legacy path, only used when backend asks
# for video_backend="daily"). One per active session.
_publishers: dict[str, asyncio.subprocess.Process] = {}

# In-process MJPEG streamers, keyed by session_id. Each is an asyncio.Task
# running stream_loop(); cancel to stop.
_streamers: dict[str, asyncio.Task] = {}

# Sessions the backend told us are active. Survives WS reconnects so the
# streamer auto-resumes when the WS comes back — without this the agent
# would silently stop publishing the screen any time its WS blipped.
# Cleared only on explicit end_session from backend.
_active_sessions: dict[str, dict[str, Any]] = {}

# Binary frame envelope (matches backend signaling.py FRAME_HEADER_LEN=8).
_FRAME_TYPE_JPEG = 1
_FRAME_HEADER_LEN = 8

# Quality string → JPEG quality factor + grayscale flag. Width/height also
# tracked separately via runtime_state for cheap downscaling.
_QUALITY_TO_JPEG: dict[str, tuple[int, bool]] = {
    "high":      (78, False),
    "medium":    (62, False),
    "low":       (45, False),
    "grayscale": (55, True),
}


def _resolve_coords(msg: dict[str, Any]) -> tuple[int, int]:
    """Pick coordinates from an input message.

    Supports two wire formats:
      - Absolute: ``{"x": 1234, "y": 567}`` — used directly.
      - Normalized: ``{"nx": 0.5, "ny": 0.5}`` — multiplied by the agent's
        own primary monitor size so the technician browser doesn't need to
        know the remote screen's resolution.
    """
    if "x" in msg and "y" in msg:
        return int(msg["x"]), int(msg["y"])
    nx = float(msg.get("nx", 0.0))
    ny = float(msg.get("ny", 0.0))
    nx = max(0.0, min(1.0, nx))
    ny = max(0.0, min(1.0, ny))
    try:
        from .screen_capture import screen_size

        w, h = screen_size()
    except Exception:
        # Headless host without a display — fall back to a sensible default.
        w, h = 1920, 1080
    return int(round(nx * (w - 1))), int(round(ny * (h - 1)))


def _build_frame(session_id: str, jpeg: bytes) -> bytes:
    """Pack a binary WS frame: header + session_id + JPEG payload.

    Layout (matches backend FRAME_HEADER_LEN=8):
        u8  type (1 = JPEG)
        u8  session_id length
        6 bytes reserved (zero — room for future flags / encoder id)
        N bytes session_id (UTF-8)
        K bytes JPEG body
    """
    sid = session_id.encode("ascii")
    if len(sid) > 255:
        raise ValueError(f"session_id too long: {len(sid)} bytes")
    header = struct.pack("<BB6x", _FRAME_TYPE_JPEG, len(sid))
    return header + sid + jpeg


async def stream_loop(session_id: str, ws: Any) -> None:
    """Capture the desktop and push JPEG frames over the WS until cancelled.

    Honors live tuning from runtime_state.json (fps / quality / monitor_index).
    The actual capture + JPEG encode is offloaded to a thread because mss +
    Pillow are blocking; running them inline would freeze the WS task and
    starve heartbeat/ping handling.
    """
    log.info("stream_loop started session=%s", session_id)
    consecutive_failures = 0
    try:
        while True:
            state = runtime_state.load()
            fps = max(1, min(30, int(state.get("fps", 8))))
            quality_label = str(state.get("quality", "medium")).lower()
            monitor_index = max(1, int(state.get("monitor_index", 1)))
            max_width = max(320, min(3840, int(state.get("width", 1280))))
            max_height = max(240, min(2160, int(state.get("height", 720))))
            jpeg_quality, grayscale = _QUALITY_TO_JPEG.get(
                quality_label, _QUALITY_TO_JPEG["medium"]
            )

            tick_started = asyncio.get_event_loop().time()
            try:
                jpeg = await asyncio.to_thread(
                    capture_frame, jpeg_quality, monitor_index,
                    max_width, max_height, grayscale,
                )
                await ws.send(_build_frame(session_id, jpeg))
                consecutive_failures = 0
            except (ConnectionClosed, OSError):
                # WS gone — let outer ws_session loop reconnect; don't spam.
                raise
            except Exception:
                consecutive_failures += 1
                if consecutive_failures <= 3 or consecutive_failures % 30 == 0:
                    log.exception("stream tick failed (n=%d)", consecutive_failures)
                if consecutive_failures > 100:
                    log.error("stream_loop giving up after 100 consecutive failures")
                    return

            elapsed = asyncio.get_event_loop().time() - tick_started
            sleep_for = max(0.0, (1.0 / fps) - elapsed)
            await asyncio.sleep(sleep_for)
    except asyncio.CancelledError:
        log.info("stream_loop cancelled session=%s", session_id)
        raise
    finally:
        log.info("stream_loop ended session=%s", session_id)


async def start_stream(session_id: str, ws: Any) -> None:
    """Launch the MJPEG streamer for a session if not already running."""
    if session_id in _streamers and not _streamers[session_id].done():
        log.warning("Streamer already running for session %s; skipping", session_id)
        return
    _streamers[session_id] = asyncio.create_task(stream_loop(session_id, ws))


async def stop_stream(session_id: str) -> None:
    task = _streamers.pop(session_id, None)
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


async def start_daily_publisher(
    session_id: str, room_url: str, meeting_token: Optional[str]
) -> None:
    """Legacy Daily.co subprocess publisher. Used only when backend sends
    video_backend="daily". Kept for back-compat / future audio support."""
    cmd = config.DAILY_PUBLISHER_CMD.strip()
    if not cmd:
        log.info("DAILY_PUBLISHER_CMD not set — skipping Daily publisher launch")
        return
    if session_id in _publishers:
        log.warning("Daily publisher already running for session %s; skipping", session_id)
        return

    env = os.environ.copy()
    env["DAILY_ROOM_URL"] = room_url
    env["DAILY_MEETING_TOKEN"] = meeting_token or ""
    env["DAILY_SESSION_ID"] = session_id

    log.info("Launching Daily publisher for session %s", session_id)
    extra: dict[str, Any] = {}
    if os.name == "posix":
        extra["start_new_session"] = True
    proc = await asyncio.create_subprocess_shell(
        cmd, env=env, stdout=None, stderr=None, **extra,
    )
    _publishers[session_id] = proc


async def stop_daily_publisher(session_id: str) -> None:
    proc = _publishers.pop(session_id, None)
    if proc is None:
        return
    if proc.returncode is None:
        log.info("Terminating Daily publisher for session %s (pid=%s)", session_id, proc.pid)
        try:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGTERM)
            else:
                proc.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            log.warning("Publisher did not exit cleanly; force-killing")
            try:
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()


async def start_session_video(
    session_id: str,
    video_backend: str,
    ws: Any,
    room_url: Optional[str],
    meeting_token: Optional[str],
) -> None:
    """Dispatch to the right publisher based on what the backend requested."""
    backend = (video_backend or "mjpeg").lower()
    if backend == "daily":
        if room_url:
            await start_daily_publisher(session_id, room_url, meeting_token)
        else:
            log.warning("video_backend=daily but no room_url; skipping")
        return
    # Default + everything else: in-process MJPEG over WS.
    await start_stream(session_id, ws)


async def stop_session_video(session_id: str) -> None:
    await stop_stream(session_id)
    await stop_daily_publisher(session_id)


async def register_if_needed() -> config.Credentials:
    creds = config.load_credentials()
    if creds:
        log.info("Loaded existing credentials machine_id=%s", creds["machine_id"])
        return creds

    payload: dict[str, Any] = {
        "name": config.MACHINE_NAME,
        "hostname": config.MACHINE_NAME,
        "os": config.detect_os(),
    }
    if config.JOIN_TOKEN:
        payload["join_token"] = config.JOIN_TOKEN
        log.info("Using Quick Connect token (one-time)")
    url = f"{config.SERVER_HTTP_URL}/machines/register"
    log.info("Registering with %s as %s/%s", url, payload["name"], payload["os"])
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        body = r.json()
    config.save_credentials(body["machine_id"], body["token"])
    if body.get("session_id"):
        log.info(
            "Quick Connect session pre-created: %s — technician will join shortly",
            body["session_id"],
        )
    log.info("Registered machine_id=%s", body["machine_id"])
    return config.Credentials(machine_id=body["machine_id"], token=body["token"])


async def heartbeat_loop(machine_id: str, token: str) -> None:
    url = f"{config.SERVER_HTTP_URL}/machines/{machine_id}/heartbeat"
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                r = await client.patch(url, params={"token": token})
                if r.status_code == 200:
                    log.debug("Heartbeat ok")
                else:
                    log.warning("Heartbeat %s: %s", r.status_code, r.text[:200])
            except Exception as e:
                log.warning("Heartbeat failed: %s", e)
            await asyncio.sleep(config.HEARTBEAT_INTERVAL_S)


async def _ask_for_consent(msg: dict[str, Any], ws: Any) -> None:
    """Prompt the local user for consent. 30s timeout = auto-deny.

    Strategy (in order of preference):
      - tkinter messagebox (works on most desktops with GUI deps installed)
      - fallback: stdout prompt with a 30s timer (only useful when the
        agent runs in a foreground terminal, e.g. dev mode)
    """
    sid = msg.get("session_id")
    tech = msg.get("technician_email", "<unknown>")

    async def _send_decision(accept: bool) -> None:
        ev = "consent_granted" if accept else "consent_denied"
        try:
            await ws.send(json.dumps({
                "type": ev,
                "session_id": sid,
                "technician_email": tech,
            }))
            log.info("consent: session=%s decision=%s", sid, ev)
            if accept and sid:
                # Now actually start video (we deferred from consent_required).
                try:
                    await start_session_video(
                        sid,
                        str(msg.get("video_backend", "mjpeg")),
                        ws,
                        msg.get("room_url"),
                        msg.get("meeting_token"),
                    )
                except Exception:
                    log.exception("Failed to start video post-consent")
        except Exception as e:
            log.warning("consent send failed: %s", e)

    decision: dict[str, bool] = {}

    def _ask_blocking() -> bool:
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            try:
                root.attributes("-topmost", True)
            except Exception:
                pass
            ans = messagebox.askyesno(
                "RemoteConnect — connection request",
                f"{tech} wants to view and control this machine.\n\nAllow?",
                parent=root,
            )
            root.destroy()
            return bool(ans)
        except Exception as e:
            log.warning("tkinter consent prompt failed (%s); auto-denying", e)
            return False

    try:
        decision["v"] = await asyncio.wait_for(
            asyncio.to_thread(_ask_blocking),
            timeout=30,
        )
    except asyncio.TimeoutError:
        log.info("consent prompt timed out — auto-deny")
        decision["v"] = False

    await _send_decision(decision["v"])


async def handle_message(msg: dict[str, Any], ws: Any) -> None:
    t = msg.get("type")
    if t == "start_session":
        sid = msg.get("session_id")
        backend = str(msg.get("video_backend", "mjpeg"))
        room_url = msg.get("room_url")
        token = msg.get("meeting_token")
        log.info(
            "start_session: session_id=%s backend=%s room_url=%s",
            sid, backend, room_url,
        )
        if sid:
            _active_sessions[sid] = {
                "video_backend": backend,
                "room_url": room_url,
                "meeting_token": token,
            }
            try:
                await start_session_video(sid, backend, ws, room_url, token)
            except Exception:
                log.exception("Failed to start video for session")
    elif t == "end_session":
        sid = msg.get("session_id")
        log.info("end_session: session_id=%s", sid)
        if sid:
            _active_sessions.pop(sid, None)
            try:
                await stop_session_video(sid)
            except Exception:
                log.exception("Failed to stop video for session")
    elif t == "consent_required":
        # Show a tray-style prompt; auto-deny after 30s. Respond with the
        # decision via the agent's WS so the backend can flip session status.
        await _ask_for_consent(msg, ws)
    elif t == "mouse_move":
        if control.input_locked():
            return
        try:
            x, y = _resolve_coords(msg)
            move_mouse(x, y)
        except Exception as e:
            log.warning("mouse_move failed: %s", e)
    elif t == "mouse_click":
        if control.input_locked():
            return
        try:
            x, y = _resolve_coords(msg)
            click_mouse(x, y, msg.get("button", "left"), msg.get("count", 1))
        except Exception as e:
            log.warning("mouse_click failed: %s", e)
    elif t == "mouse_scroll":
        if control.input_locked():
            return
        try:
            x, y = _resolve_coords(msg)
            scroll_mouse(x, y, msg.get("dx", 0), msg.get("dy", 0))
        except Exception as e:
            log.warning("mouse_scroll failed: %s", e)
    elif t == "key_press":
        if control.input_locked():
            return
        try:
            press_key(msg["key"])
        except Exception as e:
            log.warning("key_press failed: %s", e)
    elif t == "type_text":
        if control.input_locked():
            return
        try:
            type_text(msg["text"])
        except Exception as e:
            log.warning("type_text failed: %s", e)
    # ── Phase 7 commands ─────────────────────────────────────────────────
    elif t == "monitor_select":
        try:
            idx = int(msg.get("index", 1))
            runtime_state.update(monitor_index=max(1, idx))
            mons = list_monitors()
            await ws.send(json.dumps({
                "type": "monitor_list",
                "session_id": msg.get("session_id"),
                "monitors": mons,
                "selected": idx,
            }))
        except Exception as e:
            log.warning("monitor_select failed: %s", e)
    elif t == "fps_change":
        fps = max(1, min(60, int(msg.get("fps", 15))))
        runtime_state.update(fps=fps)
        log.info("fps_change applied: fps=%d", fps)
    elif t == "quality_change":
        q = str(msg.get("quality", "high")).lower()
        size_presets = {
            "high":      (1280, 720),
            "medium":    (960, 540),
            "low":       (640, 360),
            "grayscale": (960, 540),
        }
        w, h = size_presets.get(q, (1280, 720))
        runtime_state.update(quality=q, width=w, height=h)
    elif t == "clipboard_get":
        ok, text = control.clipboard_get()
        await ws.send(json.dumps({
            "type": "clipboard_data",
            "session_id": msg.get("session_id"),
            "text": text if ok else "",
            "ok": ok,
            "reason": None if ok else text,
        }))
    elif t == "clipboard_set":
        ok, detail = control.clipboard_set(msg.get("text", ""))
        if not ok:
            log.info("clipboard_set rejected: %s", detail)
    elif t == "cad_send":
        ok, detail = control.send_cad()
        log.info("cad_send: ok=%s detail=%s", ok, detail)
    elif t == "lock_screen":
        ok, detail = control.lock_screen()
        if ok:
            runtime_state.update(screen_locked=True)
        log.info("lock_screen: ok=%s detail=%s", ok, detail)
    elif t == "unlock_screen":
        ok, detail = control.unlock_screen()
        if ok:
            runtime_state.update(screen_locked=False)
        log.info("unlock_screen: ok=%s detail=%s", ok, detail)
    elif t == "input_lock":
        control.set_input_lock(True)
        runtime_state.update(input_locked=True)
    elif t == "input_unlock":
        control.set_input_lock(False)
        runtime_state.update(input_locked=False)
    elif t == "wake_lan":
        target = str(msg.get("target_mac", "")).strip()
        broadcast = msg.get("broadcast")
        ok, detail = control.send_wol(target, broadcast)
        await ws.send(json.dumps({
            "type": "wake_sent" if ok else "wake_failed",
            "mac": target,
            "reason": None if ok else detail,
        }))
    elif t in ("file_upload_start", "file_upload_cancel", "file_chunk", "file_download_request"):
        async def _send(payload: dict[str, Any]) -> None:
            await ws.send(json.dumps(payload))

        try:
            if t == "file_upload_start":
                await _transfers.on_upload_start(msg, _send)
            elif t == "file_upload_cancel":
                await _transfers.on_upload_cancel(msg, _send)
            elif t == "file_chunk":
                await _transfers.on_chunk_inbound(msg, _send)
            elif t == "file_download_request":
                await _transfers.on_download_request(msg, _send)
        except Exception:
            log.exception("file transfer handler %s failed", t)
    else:
        log.warning("Unknown message type: %r", t)


async def ws_session(machine_id: str, token: str) -> None:
    uri = f"{config.SERVER_WS_URL}/ws/agent/{machine_id}?token={token}"
    log.info("Connecting WS %s", uri.replace(token, "***"))
    # ping_timeout=15 (was 5): MJPEG sends share the same outbound TCP
    # buffer as control-plane pings, so a slow link or a beefy frame can
    # delay a pong long enough to trip a too-tight timeout. 15s leaves
    # plenty of headroom while still detecting genuinely dead sockets.
    # max_size=None disables inbound frame-size limits — control-plane
    # only, never an issue, but the default 1 MiB is needlessly tight.
    async with websockets.connect(
        uri, ping_interval=10, ping_timeout=15, close_timeout=5,
        max_size=None,
    ) as ws:
        log.info("WS connected")
        # Resume any sessions the backend last told us were active. The
        # backend won't re-send start_session on agent reconnect, so
        # without this we'd silently stop publishing the screen every
        # time the WS blips.
        for sid, st in list(_active_sessions.items()):
            log.info("Resuming streamer for active session=%s", sid)
            try:
                await start_session_video(
                    sid,
                    str(st.get("video_backend", "mjpeg")),
                    ws,
                    st.get("room_url"),
                    st.get("meeting_token"),
                )
            except Exception:
                log.exception("Failed to resume session %s on reconnect", sid)
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    log.warning("Non-JSON frame: %r", raw[:200] if isinstance(raw, str) else "<bytes>")
                    continue
                log.info("RX msg type=%s session=%s", msg.get("type"), msg.get("session_id"))
                await handle_message(msg, ws)
        finally:
            # Stop any active streamer tasks when the WS goes away — they'd
            # otherwise hang on `await ws.send()` against a dead socket.
            # _active_sessions stays populated so ws_loop's next iteration
            # can resume them.
            for sid in list(_streamers.keys()):
                await stop_stream(sid)


async def ws_loop(machine_id: str, token: str) -> None:
    """Reconnect forever. Each iteration is one full ws_session() lifecycle.

    Exceptions are logged with attempt counter so a stuck reconnect is
    obvious in the agent log instead of looking like a silent dead loop
    (the bug we hit on 2026-04-30 where the WS dropped at 10:43 and the
    log went quiet on this front while heartbeats kept firing).
    """
    attempt = 0
    backoff = 1
    while True:
        attempt += 1
        log.info("WS attempt #%d → %s", attempt, config.SERVER_WS_URL)
        try:
            await ws_session(machine_id, token)
            backoff = 1  # clean disconnect resets backoff
            log.info("WS closed cleanly; will reconnect")
        except (ConnectionClosed, OSError) as e:
            log.warning("WS dropped (attempt #%d): %s", attempt, e)
        except asyncio.CancelledError:
            log.info("WS loop cancelled")
            raise
        except Exception:
            log.exception("WS error on attempt #%d", attempt)

        wait = min(backoff, 30)
        log.info("Reconnecting in %ds (next attempt #%d)", wait, attempt + 1)
        await asyncio.sleep(wait)
        backoff = min(backoff * 2, 30)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log.info(
        "Effective config: SERVER_HTTP_URL=%s SERVER_WS_URL=%s name=%s os=%s pid=%d",
        config.SERVER_HTTP_URL, config.SERVER_WS_URL,
        config.MACHINE_NAME, config.detect_os(), os.getpid(),
    )
    creds = await register_if_needed()
    await asyncio.gather(
        heartbeat_loop(creds["machine_id"], creds["token"]),
        ws_loop(creds["machine_id"], creds["token"]),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
