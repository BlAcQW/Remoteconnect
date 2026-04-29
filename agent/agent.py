"""RemoteConnect client agent — Phase 2 MVP.

Lifecycle:
    1. On first run, register with the backend and persist credentials to
       config.json. On subsequent runs, reuse them.
    2. Run two concurrent tasks:
         - heartbeat_loop: HTTP PATCH /machines/{id}/heartbeat every N seconds
         - ws_loop: stay connected to /ws/agent/{id} with exponential-backoff
                    reconnect, dispatching commands as they arrive.
    3. Daily.co publisher launch on `start_session` is stubbed in this phase
       and will be filled in during Phase 3.
"""
import asyncio
import json
import logging
import os
import signal
import sys
from typing import Any, Optional

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from . import config, control, runtime_state
from .input_handler import click_mouse, move_mouse, press_key, scroll_mouse, type_text
from .screen_capture import list_monitors
from .transfer_handlers import TransferDispatcher

log = logging.getLogger("agent")
_transfers = TransferDispatcher()

# Active Daily.co publisher subprocess, keyed by session_id. Currently we
# only support one concurrent session (PRD max_participants=2), so the dict
# pattern just makes session-scoped teardown cleaner.
_publishers: dict[str, asyncio.subprocess.Process] = {}


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


async def start_publisher(session_id: str, room_url: str, meeting_token: Optional[str]) -> None:
    cmd = config.DAILY_PUBLISHER_CMD.strip()
    if not cmd:
        log.info("DAILY_PUBLISHER_CMD not set — skipping publisher launch (log-only mode)")
        return
    if session_id in _publishers:
        log.warning("Publisher already running for session %s; skipping", session_id)
        return

    env = os.environ.copy()
    env["DAILY_ROOM_URL"] = room_url
    env["DAILY_MEETING_TOKEN"] = meeting_token or ""
    env["DAILY_SESSION_ID"] = session_id

    log.info("Launching Daily publisher for session %s", session_id)
    # On POSIX we put the wrapper shell in its own process group so we can
    # SIGTERM the entire tree on stop_publisher (chromium etc. spawn
    # children that would otherwise be orphaned). On Windows the kwarg is
    # unsupported; fall back to default behavior + terminate().
    #
    # NOTE: stdout/stderr are inherited (None) so the publisher's logs flow
    # into the agent's own stdout. PIPE without a drainer would deadlock once
    # the OS pipe buffer fills (~64 KiB on Linux) for a long-running process.
    extra: dict[str, Any] = {}
    if os.name == "posix":
        extra["start_new_session"] = True
    proc = await asyncio.create_subprocess_shell(
        cmd,
        env=env,
        stdout=None,
        stderr=None,
        **extra,
    )
    _publishers[session_id] = proc


async def stop_publisher(session_id: str) -> None:
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
            if accept:
                # Now actually start the publisher (we deferred from start_session)
                room_url = msg.get("room_url")
                token = msg.get("meeting_token")
                if sid and room_url:
                    try:
                        await start_publisher(sid, room_url, token)
                    except Exception:
                        log.exception("Failed to start publisher post-consent")
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
        room_url = msg.get("room_url")
        token = msg.get("meeting_token")
        log.info(
            "start_session: session_id=%s room_url=%s token=%s",
            sid,
            room_url,
            "<set>" if token else "<none>",
        )
        if sid and room_url:
            try:
                await start_publisher(sid, room_url, token)
            except Exception:
                log.exception("Failed to start Daily publisher")
    elif t == "end_session":
        sid = msg.get("session_id")
        log.info("end_session: session_id=%s", sid)
        if sid:
            try:
                await stop_publisher(sid)
            except Exception:
                log.exception("Failed to stop Daily publisher")
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
    # Aggressive ping settings: detect half-closed (CLOSE-WAIT) sockets
    # within ~15s and trigger reconnect via the outer ws_loop's backoff.
    async with websockets.connect(
        uri, ping_interval=10, ping_timeout=5, close_timeout=5,
    ) as ws:
        log.info("WS connected")
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                log.warning("Non-JSON frame: %r", raw[:200])
                continue
            log.info("RX msg type=%s session=%s", msg.get("type"), msg.get("session_id"))
            await handle_message(msg, ws)


async def ws_loop(machine_id: str, token: str) -> None:
    backoff = 1
    while True:
        try:
            await ws_session(machine_id, token)
            backoff = 1  # clean disconnect resets backoff
            log.info("WS closed; will reconnect")
        except (ConnectionClosed, OSError) as e:
            log.warning("WS dropped: %s", e)
        except Exception:
            log.exception("WS error")

        wait = min(backoff, 60)
        log.info("Reconnecting in %ds", wait)
        await asyncio.sleep(wait)
        backoff = min(backoff * 2, 60)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
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
