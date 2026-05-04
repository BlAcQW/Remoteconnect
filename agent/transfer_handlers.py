"""File-transfer command handlers used by the agent's WS dispatch loop.

Wire format (matches PRD §):
    file_upload_start   tech → agent  { filename, size_bytes, total_chunks }
    file_chunk          either way    { filename, chunk_index, total_chunks, data_b64 }
    file_upload_cancel  tech → agent  { filename }
    file_download_request tech → agent { filename }   (resolved within SHARED_DIR)

Responses (agent → tech, routed via the agent's WS to the backend):
    file_upload_ack       { filename, status: "ok"|"rejected", reason? }
    file_upload_complete  { filename, size_bytes, saved_path }
    file_chunk            (download direction)
    file_download_complete { filename, size_bytes }
    file_download_error   { filename, reason }
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from . import config
from .file_transfer import FileAssembler, chunk_file

log = logging.getLogger(__name__)

# 100 MiB — must stay in lockstep with backend MAX_TRANSFER_BYTES.
MAX_TRANSFER_BYTES = 100 * 1024 * 1024

# Allowed filename pattern: no separators, no NUL, no leading dots, ≤255 chars.
_FILENAME_RE = re.compile(r"^(?!\.)[A-Za-z0-9._\- ()\[\]]{1,255}$")


def safe_filename(name: str | None) -> str | None:
    """Return ``name`` if it's a safe basename, else ``None``."""
    if not name or not isinstance(name, str):
        return None
    if "/" in name or "\\" in name or "\x00" in name:
        return None
    if not _FILENAME_RE.match(name):
        return None
    return name


def resolve_in_share(filename: str) -> Path | None:
    """Resolve ``filename`` to an absolute path inside SHARED_DIR or None."""
    target = (config.SHARED_DIR / filename).resolve()
    try:
        target.relative_to(config.SHARED_DIR)
    except ValueError:
        return None
    return target


def safe_absolute_path(raw: str | None) -> Path | None:
    """Normalize a technician-supplied absolute path. Returns the resolved
    Path or None if it's malformed.

    Why minimal restrictions: the technician already has full screen +
    keyboard control of the box at this point in the session — they can
    open Explorer and copy any file out manually. The file browser is
    a UX shortcut, not a privilege boundary. We still reject the raw
    Windows extended-length prefix because passing it through to
    Path.write_bytes / Path.is_file produces inconsistent results.
    """
    if raw is None or not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s or "\x00" in s:
        return None
    # Reject the raw extended-prefix forms — `\\?\C:\Users\...` is valid
    # to the OS but trips up Path() on some Python builds. Customers
    # don't paste these; the UI never produces them.
    if s.startswith("\\\\?\\") or s.startswith("//?/"):
        return None
    try:
        p = Path(s).resolve(strict=False)
    except (OSError, ValueError):
        return None
    return p


def resolve_download_target(filename: str | None, absolute_path: str | None) -> Path | None:
    """Pick the right resolution for a download request.

    When ``absolute_path`` is supplied the technician is browsing the
    filesystem (file_browser flow) — use it directly after sanity
    normalization. Otherwise fall back to the legacy SHARED_DIR-only
    sandbox so existing callers keep working untouched.
    """
    if absolute_path:
        p = safe_absolute_path(absolute_path)
        if p is None:
            return None
        return p
    fname = safe_filename(filename)
    if fname is None:
        return None
    return resolve_in_share(fname)


def resolve_upload_target(filename: str, dest_path: str | None) -> Path | None:
    """Pick the right resolution for an upload landing path.

    When ``dest_path`` is supplied (file_browser → "upload here"), drop
    the file as ``<dest_path>/<filename>``. Otherwise fall back to
    SHARED_DIR. ``filename`` is always validated as a basename to stop
    the upload-side path traversal vector regardless of dest_path.
    """
    fname = safe_filename(filename)
    if fname is None:
        return None
    if dest_path:
        d = safe_absolute_path(dest_path)
        if d is None:
            return None
        return d / fname
    return resolve_in_share(fname)


# Type alias for the async send-to-backend callable supplied by the caller.
SendFn = Callable[[dict[str, Any]], Awaitable[None]]


class TransferDispatcher:
    """Stateful per-agent dispatcher for file-transfer messages."""

    def __init__(self) -> None:
        self._assembler = FileAssembler()
        # Sizes/expected counts captured from the upload_start so we can sanity-check chunks.
        self._upload_meta: dict[str, dict[str, int]] = {}
        # Optional landing directory per upload, captured from upload_start
        # when the technician uses the file browser to choose a destination.
        # Cleared on completion, cancel, or rejection.
        self._upload_dest: dict[str, str] = {}

    # ── Inbound (technician → agent) ─────────────────────────────────────────
    async def on_upload_start(self, msg: dict[str, Any], send: SendFn) -> None:
        filename = safe_filename(msg.get("filename"))
        size = int(msg.get("size_bytes", 0) or 0)
        total = int(msg.get("total_chunks", 0) or 0)
        session_id = msg.get("session_id")

        if filename is None:
            await send(
                _ack(session_id, msg.get("filename"), "rejected", reason="invalid filename")
            )
            return
        if size <= 0 or size > MAX_TRANSFER_BYTES:
            await send(_ack(session_id, filename, "rejected", reason=f"bad size: {size}"))
            return
        if total <= 0 or total > 100_000:
            await send(_ack(session_id, filename, "rejected", reason=f"bad total_chunks: {total}"))
            return

        self._upload_meta[filename] = {"size": size, "total": total}
        dest = msg.get("dest_path")
        if isinstance(dest, str) and dest:
            self._upload_dest[filename] = dest
        log.info(
            "upload_start filename=%s size=%d chunks=%d dest=%s",
            filename, size, total, dest or "<shared>",
        )
        await send(_ack(session_id, filename, "ok"))

    async def on_upload_cancel(self, msg: dict[str, Any], send: SendFn) -> None:
        filename = safe_filename(msg.get("filename"))
        if filename is None:
            return
        self._assembler.cancel(filename)
        self._upload_meta.pop(filename, None)
        self._upload_dest.pop(filename, None)
        log.info("upload_cancel filename=%s", filename)

    async def on_chunk_inbound(self, msg: dict[str, Any], send: SendFn) -> None:
        filename = safe_filename(msg.get("filename"))
        session_id = msg.get("session_id")
        if filename is None or filename not in self._upload_meta:
            log.warning("Ignoring chunk for unknown/invalid upload: %r", msg.get("filename"))
            return
        try:
            index = int(msg["chunk_index"])
            total = int(msg["total_chunks"])
            b64 = msg.get("data_b64", "")
        except (KeyError, ValueError, TypeError):
            log.warning("Malformed file_chunk for %s", filename)
            return

        assembled = self._assembler.add_chunk(filename, index, total, b64)
        if assembled is None:
            return  # waiting for more chunks

        meta = self._upload_meta.pop(filename, {})
        expected = meta.get("size", 0)
        if expected and len(assembled) != expected:
            await send(
                _ack(
                    session_id,
                    filename,
                    "rejected",
                    reason=f"size mismatch: got {len(assembled)} expected {expected}",
                )
            )
            return

        dest_path = self._upload_dest.pop(filename, None)
        target = resolve_upload_target(filename, dest_path)
        if target is None:
            await send(_ack(session_id, filename, "rejected", reason="path traversal blocked"))
            return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(assembled)
        except OSError as e:
            await send(_ack(session_id, filename, "rejected", reason=f"write failed: {e}"))
            return

        log.info("upload_complete filename=%s bytes=%d -> %s", filename, len(assembled), target)
        await send(
            {
                "type": "file_upload_complete",
                "session_id": session_id,
                "filename": filename,
                "size_bytes": len(assembled),
                "saved_path": str(target),
            }
        )

    async def on_download_request(self, msg: dict[str, Any], send: SendFn) -> None:
        session_id = msg.get("session_id")
        absolute_path = msg.get("absolute_path")
        target = resolve_download_target(msg.get("filename"), absolute_path)
        # Choose what to surface back to the technician as the "filename"
        # — the basename of the resolved path is the most useful both for
        # display and for the technician's local "save as" prompt.
        display_name = (target.name if target else None) or msg.get("filename") or "?"
        if target is None:
            await send(
                {
                    "type": "file_download_error",
                    "session_id": session_id,
                    "filename": display_name,
                    "reason": "invalid path",
                }
            )
            return
        if not target.is_file():
            await send(
                {
                    "type": "file_download_error",
                    "session_id": session_id,
                    "filename": display_name,
                    "reason": "not found",
                }
            )
            return
        filename = display_name
        size = target.stat().st_size
        if size > MAX_TRANSFER_BYTES:
            await send(
                {
                    "type": "file_download_error",
                    "session_id": session_id,
                    "filename": filename,
                    "reason": f"file too large: {size}",
                }
            )
            return

        log.info("download filename=%s size=%d", filename, size)
        for index, total, b64 in chunk_file(target):
            await send(
                {
                    "type": "file_chunk",
                    "session_id": session_id,
                    "filename": filename,
                    "chunk_index": index,
                    "total_chunks": total,
                    "data_b64": b64,
                }
            )
        await send(
            {
                "type": "file_download_complete",
                "session_id": session_id,
                "filename": filename,
                "size_bytes": size,
            }
        )


def _ack(session_id: Any, filename: Any, status: str, reason: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": "file_upload_ack",
        "session_id": session_id,
        "filename": filename,
        "status": status,
    }
    if reason:
        out["reason"] = reason
    return out
