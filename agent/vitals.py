"""Real-time vitals streamer.

The technician panel sends `vitals_subscribe` once when it opens; the
agent ticks every `interval_s` (default 1.0s) sending a small
`vitals_tick` JSON. `vitals_unsubscribe` (or WS drop, or session end)
stops the loop.

Each sample is intentionally tiny — under 200 bytes — so the panel can
keep a 60-sample sparkline without bloat. Heavy data (per-disk IO,
per-process top-N) belongs in dedicated panels.

Pattern: this is the first agent-side push subscription in the protocol.
The shape (subscribe → server pushes ticks → unsubscribe) is what we'll
reuse for log-tailing, alerting, etc.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

DEFAULT_INTERVAL_S = 1.0
MIN_INTERVAL_S = 0.5
MAX_INTERVAL_S = 10.0

SendFn = Callable[[dict[str, Any]], Awaitable[None]]


def _sample_once() -> dict[str, Any]:
    """Build one vitals_tick payload. Cheap — one psutil call per axis."""
    import psutil

    # cpu_percent(interval=None) is non-blocking; the value is the delta
    # since the last call by the same process. We seed the loop with one
    # call at start so the first real tick is meaningful.
    cpu = float(psutil.cpu_percent(interval=None))
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    # Disk IO and net IO are cumulative — the panel can render rates by
    # diffing successive samples. Send the cumulative bytes; let the UI
    # do the math.
    diskio = psutil.disk_io_counters() if hasattr(psutil, "disk_io_counters") else None
    netio = psutil.net_io_counters() if hasattr(psutil, "net_io_counters") else None

    out: dict[str, Any] = {
        "ts": time.time(),
        "cpu_pct": round(cpu, 1),
        "mem_total_mb": round(vm.total / (1024 * 1024)),
        "mem_used_pct": round(float(vm.percent), 1),
        "swap_used_pct": round(float(sw.percent), 1),
    }
    if diskio:
        out["disk_read_bytes"] = int(diskio.read_bytes)
        out["disk_write_bytes"] = int(diskio.write_bytes)
    if netio:
        out["net_recv_bytes"] = int(netio.bytes_recv)
        out["net_sent_bytes"] = int(netio.bytes_sent)
    return out


class VitalsStreamer:
    """One per agent process. Multiple subscribe calls coalesce — there's
    only one streamer task even if several panels open. Last interval
    wins (panels with different rates aren't a real workflow yet)."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._interval_s = DEFAULT_INTERVAL_S
        self._send: SendFn | None = None
        self._session_id: str | None = None

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(
        self,
        send: SendFn,
        session_id: str | None,
        interval_s: float = DEFAULT_INTERVAL_S,
    ) -> None:
        clamped = max(MIN_INTERVAL_S, min(MAX_INTERVAL_S, float(interval_s)))
        self._interval_s = clamped
        self._send = send
        self._session_id = session_id
        if self.is_running():
            log.info("vitals already running, refreshed interval=%.2fs", clamped)
            return
        self._stop.clear()
        # Prime psutil's cpu_percent so the first sample isn't 0.
        try:
            import psutil

            psutil.cpu_percent(interval=None)
        except Exception:
            pass
        self._task = asyncio.create_task(self._loop())
        log.info("vitals streamer started interval=%.2fs", clamped)

    async def stop(self) -> None:
        if not self.is_running():
            return
        self._stop.set()
        try:
            assert self._task is not None
            await asyncio.wait_for(self._task, timeout=2.0)
        except (asyncio.TimeoutError, AssertionError):
            if self._task:
                self._task.cancel()
        self._task = None
        log.info("vitals streamer stopped")

    async def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                send = self._send
                if send is None:
                    return
                try:
                    payload = await asyncio.to_thread(_sample_once)
                except Exception:
                    log.exception("vitals sample failed")
                    payload = {"ts": time.time(), "error": "sample_failed"}
                payload["type"] = "vitals_tick"
                payload["session_id"] = self._session_id
                try:
                    await send(payload)
                except Exception:
                    log.exception("vitals send failed; stopping")
                    return
                # asyncio.wait lets us wake on stop without hanging out the
                # full interval after stop() is called.
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self._interval_s)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            return


_singleton = VitalsStreamer()


def streamer() -> VitalsStreamer:
    return _singleton
