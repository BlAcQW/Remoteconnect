"""Folder send / receive for the Transfer tab in FileBrowserPanel.

folder_send       – zip a local folder and push it to the technician as a
                    chunked file download (reuses the existing file-transfer
                    chunk protocol so the frontend download works unchanged).
folder_receive    – receive a zip from the technician, unpack to the
                    configured receive folder.
receive_folder_*  – get / set / open the local destination folder.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import platform
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

_receive_folder: str = str(Path.home() / "Downloads" / "RemoteConnect")

SendFn = Callable[[dict[str, Any]], Awaitable[None]]

CHUNK_SIZE = 64 * 1024  # 64 KiB per chunk


# ── receive folder helpers ──────────────────────────────────────────────────

def get_receive_folder() -> str:
    return _receive_folder


def set_receive_folder(path: str) -> bool:
    global _receive_folder
    try:
        p = Path(path).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        _receive_folder = str(p)
        log.info("Receive folder set to %s", _receive_folder)
        return True
    except Exception:
        log.exception("Failed to set receive folder to %r", path)
        return False


def open_receive_folder() -> None:
    try:
        p = Path(_receive_folder)
        p.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(p))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
    except Exception:
        log.exception("Failed to open receive folder")


# ── folder → zip → chunked download ────────────────────────────────────────

async def send_folder(path: str, request_id: str, send: SendFn) -> None:
    """Zip the folder at *path* and push it to the tech as chunked frames."""
    src = Path(path)
    if not src.is_dir():
        await send({"type": "folder_send_error", "request_id": request_id,
                    "error": f"Not a directory: {path}"})
        return

    try:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(src):
                for fname in files:
                    fpath = Path(root) / fname
                    arcname = fpath.relative_to(src.parent)
                    try:
                        zf.write(fpath, arcname)
                    except (PermissionError, OSError):
                        pass  # skip inaccessible files
        data   = buf.getvalue()
        total  = len(data)
        chunks = (total + CHUNK_SIZE - 1) // CHUNK_SIZE

        await send({
            "type":       "folder_send_start",
            "request_id": request_id,
            "filename":   src.name + ".zip",
            "size":       total,
            "chunks":     chunks,
        })

        for i in range(chunks):
            chunk = data[i * CHUNK_SIZE: (i + 1) * CHUNK_SIZE]
            await send({
                "type":       "folder_send_chunk",
                "request_id": request_id,
                "index":      i,
                "data":       chunk.hex(),
            })
            await asyncio.sleep(0)  # yield between chunks

        await send({"type": "folder_send_complete", "request_id": request_id})
        log.info("folder_send complete: %s (%d bytes)", path, total)

    except Exception:
        log.exception("folder_send failed for %r", path)
        await send({"type": "folder_send_error", "request_id": request_id,
                    "error": "Zip/send failed — check agent log"})


# ── receive zip chunks, unpack ──────────────────────────────────────────────

_pending_receives: dict[str, dict[str, Any]] = {}


async def receive_start(msg: dict[str, Any], send: SendFn) -> None:
    rid      = msg.get("request_id", "")
    filename = msg.get("filename", "received.zip")
    chunks   = int(msg.get("chunks", 0))
    _pending_receives[rid] = {
        "filename": filename,
        "chunks":   chunks,
        "parts":    {},
    }
    await send({"type": "folder_receive_ack", "request_id": rid})


async def receive_chunk(msg: dict[str, Any], send: SendFn) -> None:
    rid   = msg.get("request_id", "")
    index = int(msg.get("index", 0))
    data  = bytes.fromhex(msg.get("data", ""))
    rec   = _pending_receives.get(rid)
    if rec is None:
        return
    rec["parts"][index] = data
    if len(rec["parts"]) >= rec["chunks"]:
        await _finalise(rid, rec, send)


async def _finalise(rid: str, rec: dict[str, Any], send: SendFn) -> None:
    try:
        raw = b"".join(rec["parts"][i] for i in range(rec["chunks"]))
        dest = Path(_receive_folder)
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            zf.extractall(dest)
        log.info("folder_receive unpacked to %s", dest)
        await send({"type": "folder_transfer_result", "request_id": rid,
                    "success": True, "path": str(dest)})
    except Exception as e:
        log.exception("folder_receive unpack failed for rid=%s", rid)
        await send({"type": "folder_transfer_result", "request_id": rid,
                    "success": False, "error": str(e)})
    finally:
        _pending_receives.pop(rid, None)
