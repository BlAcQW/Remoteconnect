"""Hidden shell — execute one-shot commands without showing a console
window on the customer's desktop. Output streams back to the technician
as base64 chunks; a final shell_complete reports the exit code.

Design notes:
- One-shot per command. No persistent shell state — `cd`, env vars don't
  carry between requests. Trade-off chosen for v1; revisit if customers
  ask for an interactive REPL.
- stdout and stderr are both captured but tagged so the UI can color
  stderr differently. Combined output ordering is preserved per stream.
- CREATE_NO_WINDOW (Windows) / start_new_session (POSIX) keep the
  subprocess invisible. The agent itself runs without a console (the
  bundled .exe is built --noconsole).
- Cancellation is by request_id. The dispatcher in agent.py keeps a
  table of {request_id: ShellRun} and forwards `shell_cancel` here.
- Output cap (TOTAL_BYTE_CAP) prevents runaway commands from exhausting
  memory or saturating the WS. When exceeded the run is terminated and
  shell_complete is emitted with error="output_truncated".
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

# Hard ceilings. These backstop the server-side validation in
# backend/routers/signaling.py and stop a misbehaving frontend or
# bypassed validator from blowing up the agent.
TOTAL_BYTE_CAP = 5 * 1024 * 1024  # 5 MiB combined stdout+stderr
CHUNK_FLUSH_BYTES = 4 * 1024  # send a chunk roughly every 4 KiB
CHUNK_FLUSH_INTERVAL_S = 0.1  # ...or every 100 ms, whichever first
TERMINATE_GRACE_S = 5.0  # SIGTERM → wait → SIGKILL window
SUPPORTED_SHELLS = {"cmd", "powershell", "bash", "sh"}

# Send callback type: receives a JSON-serializable dict and ships it
# over the agent's WS. Using a callback decouples this module from the
# WS object so it's easy to test.
SendFn = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class ShellRun:
    request_id: str
    proc: asyncio.subprocess.Process
    task: asyncio.Task
    bytes_sent: int = 0
    cancelled: bool = False
    error: str | None = None
    started_at: float = field(default_factory=time.monotonic)


def _shell_command(shell: str, command: str) -> tuple[list[str], dict[str, int]]:
    """Translate (shell, command) into a process invocation.

    Returns (argv, kwargs-extra) where kwargs-extra is platform-specific
    process-creation tweaks (CREATE_NO_WINDOW, start_new_session)."""
    shell = (shell or "").lower()
    if shell == "cmd":
        argv = ["cmd.exe", "/c", command]
    elif shell == "powershell":
        # -NoProfile keeps startup fast and avoids running customer
        # PowerShell profile scripts that might prompt or hang.
        argv = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
    elif shell == "bash":
        argv = ["bash", "-c", command]
    elif shell == "sh":
        argv = ["sh", "-c", command]
    else:
        # Pick a sensible default per OS.
        if sys.platform == "win32":
            argv = ["cmd.exe", "/c", command]
        else:
            argv = ["sh", "-c", command]

    extra: dict[str, int] = {}
    if sys.platform == "win32":
        # 0x08000000 = CREATE_NO_WINDOW. Without this the subprocess
        # flashes a console window on screen for the user to see.
        extra["creationflags"] = 0x08000000
    else:
        # Make a new process group so we can SIGTERM the whole tree on
        # cancel (a shell -c can spawn children). On POSIX,
        # asyncio.create_subprocess_exec accepts start_new_session.
        extra["start_new_session"] = True  # type: ignore[assignment]
    return argv, extra


async def _stream_pipe(
    stream: asyncio.StreamReader | None,
    stream_name: str,
    run: ShellRun,
    send: SendFn,
    session_id: str | None,
) -> None:
    """Drain `stream`, base64-chunking the bytes back to the technician.
    Flushes opportunistically every CHUNK_FLUSH_BYTES or
    CHUNK_FLUSH_INTERVAL_S, whichever fires first."""
    if stream is None:
        return
    buf = bytearray()
    last_flush = time.monotonic()
    while True:
        try:
            data = await stream.read(4096)
        except (asyncio.CancelledError, ConnectionResetError):
            break
        if not data:
            break
        buf.extend(data)
        now = time.monotonic()
        ready = len(buf) >= CHUNK_FLUSH_BYTES or (now - last_flush) >= CHUNK_FLUSH_INTERVAL_S
        if ready:
            # Cap check happens *before* send so we don't ship past the
            # cap and surface a misleading byte count.
            remaining = TOTAL_BYTE_CAP - run.bytes_sent
            if remaining <= 0:
                run.error = "output_truncated"
                _terminate(run.proc)
                break
            payload = bytes(buf[:remaining])
            buf = buf[len(payload):]
            run.bytes_sent += len(payload)
            try:
                await send({
                    "type": "shell_chunk",
                    "request_id": run.request_id,
                    "session_id": session_id,
                    "stream": stream_name,
                    "data_b64": base64.b64encode(payload).decode("ascii"),
                })
            except Exception:
                log.exception("shell_chunk send failed; aborting stream")
                run.error = "send_failed"
                _terminate(run.proc)
                break
            last_flush = now
            if run.error == "output_truncated":
                break
    # Final flush of any tail bytes.
    if buf and run.error not in ("output_truncated", "send_failed"):
        run.bytes_sent += len(buf)
        try:
            await send({
                "type": "shell_chunk",
                "request_id": run.request_id,
                "session_id": session_id,
                "stream": stream_name,
                "data_b64": base64.b64encode(bytes(buf)).decode("ascii"),
            })
        except Exception:
            log.exception("final shell_chunk send failed")


def _terminate(proc: asyncio.subprocess.Process) -> None:
    """Best-effort SIGTERM. The reaper task in `run()` handles SIGKILL
    escalation if needed."""
    try:
        if proc.returncode is None:
            proc.terminate()
    except ProcessLookupError:
        pass
    except Exception:
        log.exception("terminate failed")


async def run(
    request_id: str,
    shell: str,
    command: str,
    timeout_s: int,
    session_id: str | None,
    send: SendFn,
) -> ShellRun:
    """Start a one-shot command and ship streamed output via `send`.

    Returns the ShellRun handle so the caller can store it for cancel
    dispatch. The caller does NOT await this function — the actual
    streaming happens in the spawned task. shell_complete is sent
    automatically when the task finishes.
    """
    started = time.monotonic()
    argv, extra = _shell_command(shell, command)

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **extra,
        )
    except FileNotFoundError as e:
        await send({
            "type": "shell_complete",
            "request_id": request_id,
            "session_id": session_id,
            "exit_code": -1,
            "duration_ms": 0,
            "error": f"shell not available: {e}",
        })
        # Return a sentinel run with already-finished task so the caller
        # can drop it from its registry without crashing.
        async def _noop() -> None:
            return
        return ShellRun(request_id=request_id, proc=_DeadProc(), task=asyncio.create_task(_noop()))
    except Exception as e:
        await send({
            "type": "shell_complete",
            "request_id": request_id,
            "session_id": session_id,
            "exit_code": -1,
            "duration_ms": 0,
            "error": f"spawn failed: {e}",
        })
        async def _noop2() -> None:
            return
        return ShellRun(request_id=request_id, proc=_DeadProc(), task=asyncio.create_task(_noop2()))

    run_handle = ShellRun(request_id=request_id, proc=proc, task=None)  # type: ignore[arg-type]

    async def _driver() -> None:
        # Drain stdout and stderr concurrently. Apply timeout via
        # asyncio.wait_for around the gather so a stuck process gets
        # SIGTERM after `timeout_s` seconds.
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    _stream_pipe(proc.stdout, "stdout", run_handle, send, session_id),
                    _stream_pipe(proc.stderr, "stderr", run_handle, send, session_id),
                ),
                timeout=max(1, int(timeout_s)),
            )
            exit_code = await proc.wait()
        except asyncio.TimeoutError:
            run_handle.error = "timeout"
            _terminate(proc)
            try:
                exit_code = await asyncio.wait_for(proc.wait(), timeout=TERMINATE_GRACE_S)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                exit_code = await proc.wait()
        except asyncio.CancelledError:
            run_handle.cancelled = True
            _terminate(proc)
            try:
                exit_code = await asyncio.wait_for(proc.wait(), timeout=TERMINATE_GRACE_S)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                exit_code = await proc.wait()
        except Exception as e:
            run_handle.error = run_handle.error or f"driver error: {e}"
            _terminate(proc)
            try:
                exit_code = await proc.wait()
            except Exception:
                exit_code = -1

        duration_ms = int((time.monotonic() - run_handle.started_at) * 1000)
        try:
            await send({
                "type": "shell_complete",
                "request_id": request_id,
                "session_id": session_id,
                "exit_code": int(exit_code) if exit_code is not None else -1,
                "duration_ms": duration_ms,
                "error": run_handle.error,
                "cancelled": run_handle.cancelled,
                "bytes_sent": run_handle.bytes_sent,
            })
        except Exception:
            log.exception("shell_complete send failed")

    run_handle.task = asyncio.create_task(_driver())
    log.info("shell_run started request_id=%s shell=%s timeout=%ds", request_id, shell, timeout_s)
    return run_handle


class _DeadProc:
    """Stand-in for a Process when spawn failed. Lets the caller treat
    every ShellRun the same (e.g. `.cancel()`) without None checks."""
    returncode: int | None = -1

    def terminate(self) -> None: ...
    def kill(self) -> None: ...
    async def wait(self) -> int:
        return -1


async def cancel(handle: ShellRun) -> None:
    """Cancel an in-flight run. Safe to call multiple times."""
    if handle.task and not handle.task.done():
        handle.cancelled = True
        handle.task.cancel()
