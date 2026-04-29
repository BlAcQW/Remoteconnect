"""RemoteConnect Daily.co publisher.

Joins a Daily room as a video-only publisher, captures the agent's primary
monitor with mss, and feeds RGBA frames into a `VirtualCameraDevice` at the
configured framerate. Designed to be invoked by `agent.agent.start_publisher`
via ``DAILY_PUBLISHER_CMD``.

Required env vars (populated by the agent):
    DAILY_ROOM_URL        e.g. https://yourteam.daily.co/session-abc
    DAILY_MEETING_TOKEN   short-lived meeting token (may be empty for public rooms)
    DAILY_SESSION_ID      RemoteConnect session UUID (informational)

Optional tuning:
    PUBLISHER_FPS         default 15
    PUBLISHER_WIDTH       default 1280
    PUBLISHER_HEIGHT      default 720
    PUBLISHER_LOG_LEVEL   default INFO
    PUBLISHER_DRY_RUN     "1" to exercise the SDK init path without joining
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from typing import Any, Optional

logging.basicConfig(
    level=os.getenv("PUBLISHER_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s publisher: %(message)s",
)
log = logging.getLogger("publisher")

_stop = threading.Event()


def _on_signal(signum: int, _frame: Any) -> None:
    log.info("received signal %s, shutting down", signum)
    _stop.set()


def _require_env() -> tuple[str, Optional[str], str]:
    try:
        room = os.environ["DAILY_ROOM_URL"]
    except KeyError:
        log.error("DAILY_ROOM_URL is required")
        raise
    token = os.environ.get("DAILY_MEETING_TOKEN") or None
    session_id = os.environ.get("DAILY_SESSION_ID", "?")
    return room, token, session_id


def main() -> int:
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    try:
        room_url, token, session_id = _require_env()
    except KeyError:
        return 2

    fps = max(1, int(os.environ.get("PUBLISHER_FPS", "15")))
    width = int(os.environ.get("PUBLISHER_WIDTH", "1280"))
    height = int(os.environ.get("PUBLISHER_HEIGHT", "720"))
    dry_run = os.environ.get("PUBLISHER_DRY_RUN") == "1"

    try:
        import daily
    except ImportError as e:
        log.error(
            "daily-python not installed: %s. "
            "Run: %s/pip install daily-python",
            e,
            os.path.dirname(sys.executable),
        )
        return 3

    log.info(
        "session=%s starting %dx%d @ %dfps -> %s",
        session_id,
        width,
        height,
        fps,
        room_url,
    )

    daily.Daily.init()
    try:
        camera = daily.Daily.create_camera_device(
            "remoteconnect_screen",
            width=width,
            height=height,
            color_format="RGBA",
        )
        client = daily.CallClient()
        try:
            client.set_user_name(f"agent-{session_id[:8]}")
            client.update_inputs(
                {
                    "camera": {
                        "isEnabled": True,
                        "settings": {"deviceId": "remoteconnect_screen"},
                    },
                    "microphone": False,
                }
            )
            client.update_publishing(
                {"camera": {"sendSettings": {"maxQuality": "low"}}}
            )

            if dry_run:
                log.info("PUBLISHER_DRY_RUN=1 — skipping join, exiting cleanly")
                return 0

            if not _join(client, room_url, token):
                return 4
            if not _capture_loop(camera, fps, width, height):
                return 5
        finally:
            _leave(client)
            client.release()
    finally:
        daily.Daily.deinit()
    return 0


def _join(client: Any, room_url: str, token: Optional[str]) -> bool:
    join_event = threading.Event()
    join_data: dict[str, Any] = {}

    def on_join(data: Any, error: Any) -> None:
        join_data["error"] = error
        join_data["data"] = data
        join_event.set()

    client.join(meeting_url=room_url, meeting_token=token, completion=on_join)
    if not join_event.wait(timeout=20):
        log.error("join timeout")
        return False
    if join_data.get("error"):
        log.error("join failed: %s", join_data["error"])
        return False
    log.info("joined room")
    return True


def _leave(client: Any) -> None:
    leave_event = threading.Event()
    try:
        client.leave(completion=lambda *_a: leave_event.set())
    except Exception as e:
        log.warning("leave call raised: %s", e)
        return
    leave_event.wait(timeout=5)
    log.info("left room")


def _capture_loop(camera: Any, fps: int, width: int, height: int) -> bool:
    """Block until _stop fires, pumping screen frames into ``camera``.

    Each iteration reads agent/.runtime_state.json so the technician can
    change FPS/quality/monitor mid-session without restarting the publisher.
    The state file is tiny so the read is cheap (<1ms)."""
    try:
        import mss
        from PIL import Image, ImageOps
    except ImportError as e:
        log.error("missing capture deps (mss/Pillow): %s", e)
        return False

    try:
        from . import runtime_state
    except ImportError:
        runtime_state = None  # type: ignore[assignment]

    cur_fps = max(1, fps)
    cur_w, cur_h = width, height
    cur_monitor = 1
    cur_quality = "high"
    last_state_check = 0.0

    frames = 0
    last_log = time.monotonic()
    with mss.mss() as sct:
        while not _stop.is_set():
            t0 = time.monotonic()

            # Re-check runtime state every ~250ms
            if runtime_state and (t0 - last_state_check) > 0.25:
                last_state_check = t0
                st = runtime_state.load()
                cur_fps = max(1, int(st.get("fps") or fps))
                cur_w = int(st.get("width") or width)
                cur_h = int(st.get("height") or height)
                cur_monitor = int(st.get("monitor_index") or 1)
                cur_quality = str(st.get("quality") or "high")

            try:
                mon = sct.monitors[cur_monitor] if 0 < cur_monitor < len(sct.monitors) else sct.monitors[1]
                raw = sct.grab(mon)
                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
                if img.size != (cur_w, cur_h):
                    img = img.resize((cur_w, cur_h), Image.BILINEAR)
                if cur_quality == "grayscale":
                    img = ImageOps.grayscale(img).convert("RGB")
                img = img.convert("RGBA")
                camera.write_frame(img.tobytes())
                frames += 1
            except Exception as e:
                log.warning("frame capture error: %s", e)

            now = time.monotonic()
            if now - last_log >= 10:
                log.info(
                    "published %d frames in last %.0fs (fps=%d quality=%s mon=%d size=%dx%d)",
                    frames, now - last_log, cur_fps, cur_quality, cur_monitor, cur_w, cur_h,
                )
                frames = 0
                last_log = now

            period = 1.0 / cur_fps
            elapsed = time.monotonic() - t0
            if elapsed < period:
                _stop.wait(period - elapsed)
    return True


if __name__ == "__main__":
    sys.exit(main())
