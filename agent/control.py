"""Platform-specific control surfaces called from the WS handler loop.

Each function returns ``(ok: bool, detail: str)``. We log + report status
back to the technician rather than raising, since most of these features
are best-effort and the UI should reflect "tried and failed" gracefully.

The hard cases (Ctrl+Alt+Del, blank-screen, input-lock) are NOT
production-grade implementations — they're scaffolds that work where the
OS allows and degrade cleanly where it doesn't. See agent/install/README.md
for limitations.
"""
from __future__ import annotations

import logging
import platform
import socket
import struct
import threading
from typing import Optional, Tuple

log = logging.getLogger(__name__)

OS = platform.system().lower()  # 'linux' | 'darwin' | 'windows'

# ── Clipboard ─────────────────────────────────────────────────────────────
def clipboard_get() -> Tuple[bool, str]:
    try:
        import pyperclip
    except ImportError:
        return False, "pyperclip not installed"
    try:
        return True, pyperclip.paste() or ""
    except Exception as e:
        return False, f"paste failed: {e}"


def clipboard_set(text: str) -> Tuple[bool, str]:
    try:
        import pyperclip
    except ImportError:
        return False, "pyperclip not installed"
    try:
        pyperclip.copy(str(text))
        return True, "ok"
    except Exception as e:
        return False, f"copy failed: {e}"


# ── Ctrl+Alt+Del (Secure Attention Sequence) ──────────────────────────────
def send_cad() -> Tuple[bool, str]:
    """Inject Ctrl+Alt+Del.

    On Windows: requires ``sas.dll`` (Secure Attention Sequence) and an
    elevated agent process. The DLL is part of the Microsoft Plus! pack
    on older systems and shipped with later Windows; absence is reported
    cleanly.

    On macOS / Linux: not applicable. Logged and returned as unsupported.
    """
    if "windows" not in OS:
        return False, f"not supported on {OS}"
    try:
        import ctypes
        sas = ctypes.WinDLL("sas.dll")  # type: ignore[attr-defined]
        # SendSAS(BOOL AsUser) — passing 0 sends as the system service.
        sas.SendSAS(0)
        return True, "ok"
    except OSError as e:
        return False, f"sas.dll unavailable: {e}"
    except Exception as e:
        return False, f"SendSAS failed: {e}"


# ── Lock / blank screen (best-effort fullscreen black) ────────────────────
_lock_thread: Optional[threading.Thread] = None
_lock_root = None


def lock_screen() -> Tuple[bool, str]:
    """Display a fullscreen black window with a "Session in progress…"
    label. Best-effort: the user can usually still Alt+Tab out of it. For
    a real "secure desktop" you'd need Windows Workstation API or a Linux
    compositor lock — outside the scope of this implementation."""
    global _lock_thread, _lock_root
    if _lock_root is not None:
        return True, "already locked"
    try:
        import tkinter as tk
    except ImportError:
        return False, "tkinter not available"

    started = threading.Event()
    err: list[str] = []

    def run():
        global _lock_root
        try:
            root = tk.Tk()
            root.configure(bg="black")
            root.attributes("-fullscreen", True)
            try:
                root.attributes("-topmost", True)
            except Exception:
                pass
            tk.Label(
                root, text="Session in progress — controlled remotely",
                bg="black", fg="#9aa0a6", font=("Helvetica", 24),
            ).pack(expand=True)
            _lock_root = root
            started.set()
            root.mainloop()
        except Exception as e:  # noqa: BLE001
            err.append(str(e))
            started.set()

    _lock_thread = threading.Thread(target=run, daemon=True, name="rc-lock-screen")
    _lock_thread.start()
    started.wait(timeout=2)
    if err:
        return False, err[0]
    return True, "locked"


def unlock_screen() -> Tuple[bool, str]:
    global _lock_root, _lock_thread
    if _lock_root is None:
        return True, "not locked"
    try:
        _lock_root.after(0, _lock_root.destroy)
    except Exception as e:
        return False, f"destroy failed: {e}"
    _lock_root = None
    _lock_thread = None
    return True, "unlocked"


# ── Input lock state (agent-side gate, not OS-level) ──────────────────────
_input_locked = False


def set_input_lock(locked: bool) -> Tuple[bool, str]:
    """Tell agent to drop incoming physical input *attempts* to interrupt
    the technician. This is **not** OS-level — physical mouse/keyboard
    still work. It only changes whether the agent itself accepts new
    technician input. (Useful as a placeholder for the real OS-level lock
    a kernel driver would provide.)"""
    global _input_locked
    _input_locked = bool(locked)
    return True, "locked" if _input_locked else "unlocked"


def input_locked() -> bool:
    return _input_locked


# ── Wake-on-LAN ───────────────────────────────────────────────────────────
def send_wol(mac: str, broadcast: Optional[str] = None) -> Tuple[bool, str]:
    """Send the magic packet to UDP/9 on the given (or default) broadcast."""
    cleaned = mac.replace(":", "").replace("-", "").upper()
    if len(cleaned) != 12:
        return False, "invalid MAC"
    try:
        mac_bytes = bytes.fromhex(cleaned)
    except ValueError:
        return False, "invalid MAC hex"

    packet = b"\xff" * 6 + mac_bytes * 16
    target = broadcast or "255.255.255.255"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(packet, (target, 9))
        return True, f"sent to {target}"
    except OSError as e:
        return False, f"socket: {e}"
