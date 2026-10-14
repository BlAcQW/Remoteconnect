"""Bidirectional clipboard synchronisation.

When enabled the agent polls the local clipboard every second and sends
clipboard_data to the technician when content changes. Incoming
clipboard_set messages from the tech side write back to local clipboard.

Windows: ctypes / win32clipboard
Linux:   xclip / xsel subprocess fallback
macOS:   pbpaste / pbcopy subprocess fallback
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from typing import Callable, Awaitable

log = logging.getLogger(__name__)

_enabled   = False
_last_text = ""
_task: asyncio.Task | None = None


# ── platform clipboard read/write ─────────────────────────────────────────

def _read() -> str:
    try:
        if sys.platform == "win32":
            import ctypes
            user32 = ctypes.windll.user32
            if not user32.OpenClipboard(0):
                return ""
            try:
                CF_UNICODETEXT = 13
                h = ctypes.windll.user32.GetClipboardData(CF_UNICODETEXT)
                if not h:
                    return ""
                ptr = ctypes.windll.kernel32.GlobalLock(h)
                text = ctypes.wstring_at(ptr)
                ctypes.windll.kernel32.GlobalUnlock(h)
                return text
            finally:
                user32.CloseClipboard()
        elif sys.platform == "darwin":
            return subprocess.check_output(["pbpaste"], timeout=2).decode("utf-8", "replace")
        else:
            for cmd in (["xclip", "-selection", "clipboard", "-o"],
                        ["xsel", "--clipboard", "--output"]):
                try:
                    return subprocess.check_output(cmd, timeout=2, stderr=subprocess.DEVNULL).decode("utf-8", "replace")
                except FileNotFoundError:
                    continue
    except Exception:
        pass
    return ""


def _write(text: str) -> None:
    try:
        if sys.platform == "win32":
            import ctypes
            user32   = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            if not user32.OpenClipboard(0):
                return
            try:
                user32.EmptyClipboard()
                CF_UNICODETEXT = 13
                encoded = (text + "\0").encode("utf-16-le")
                h = kernel32.GlobalAlloc(0x0002, len(encoded))
                ptr = kernel32.GlobalLock(h)
                ctypes.memmove(ptr, encoded, len(encoded))
                kernel32.GlobalUnlock(h)
                user32.SetClipboardData(CF_UNICODETEXT, h)
            finally:
                user32.CloseClipboard()
        elif sys.platform == "darwin":
            proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            proc.communicate(input=text.encode("utf-8"), timeout=2)
        else:
            for cmd in (["xclip", "-selection", "clipboard"],
                        ["xsel", "--clipboard", "--input"]):
                try:
                    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
                    proc.communicate(input=text.encode("utf-8"), timeout=2)
                    return
                except FileNotFoundError:
                    continue
    except Exception:
        log.exception("clipboard write failed")


# ── polling loop ───────────────────────────────────────────────────────────

async def _poll(send: Callable[[dict], Awaitable[None]]) -> None:
    global _last_text
    while _enabled:
        try:
            text = _read()
            if text and text != _last_text:
                _last_text = text
                await send({"type": "clipboard_data", "text": text, "source": "agent"})
        except Exception:
            log.exception("clipboard poll error")
        await asyncio.sleep(1.0)


def enable(send: Callable[[dict], Awaitable[None]]) -> None:
    global _enabled, _task
    if _enabled:
        return
    _enabled = True
    _task = asyncio.ensure_future(_poll(send))
    log.info("Clipboard sync enabled")


def disable() -> None:
    global _enabled, _task
    _enabled = False
    if _task and not _task.done():
        _task.cancel()
    _task = None
    log.info("Clipboard sync disabled")


def write_remote(text: str) -> None:
    """Called when the tech pushes clipboard content to the agent."""
    global _last_text
    _write(text)
    _last_text = text  # avoid echo-back
