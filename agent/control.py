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


# ── Power actions: reboot / shutdown / log off ────────────────────────────
def _power_windows(verb: str, delay_s: int, message: str) -> Tuple[bool, str]:
    """Schedule a power action via shutdown.exe. Customer sees a system
    notification countdown for `delay_s` seconds before the action fires.

    `shutdown.exe` flag map:
      reboot   → /r
      shutdown → /s
      logoff   → /l    (logoff ignores /t and /c; fires immediately)
    """
    import subprocess

    flag_map = {"reboot": "/r", "shutdown": "/s", "logoff": "/l"}
    flag = flag_map.get(verb)
    if flag is None:
        return False, f"unknown verb: {verb}"

    if verb == "logoff":
        # /t and /c aren't valid with /l — fire immediately.
        cmd = ["shutdown", flag, "/f"]
    else:
        cmd = ["shutdown", flag, "/t", str(int(delay_s)), "/c", message[:255]]
    try:
        # CREATE_NO_WINDOW so the customer doesn't see a stray cmd flicker.
        creationflags = 0x08000000  # CREATE_NO_WINDOW
        completed = subprocess.run(
            cmd, capture_output=True, timeout=10, creationflags=creationflags,
        )
        if completed.returncode == 0:
            return True, "scheduled"
        err = completed.stderr.decode(errors="replace").strip() or completed.stdout.decode(errors="replace").strip()
        return False, f"shutdown.exe rc={completed.returncode}: {err}"
    except FileNotFoundError:
        return False, "shutdown.exe not found"
    except subprocess.TimeoutExpired:
        return False, "shutdown.exe timed out"


def _power_macos(verb: str, delay_s: int, message: str) -> Tuple[bool, str]:
    """macOS power via osascript. Sudo-free for the current user, requires
    the agent to run inside an interactive session (it does, by design)."""
    import subprocess

    if verb == "reboot":
        script = 'tell application "System Events" to restart'
    elif verb == "shutdown":
        script = 'tell application "System Events" to shut down'
    elif verb == "logoff":
        script = 'tell application "System Events" to log out'
    else:
        return False, f"unknown verb: {verb}"

    if delay_s > 0:
        # `osascript` runs immediately; emulate the delay with `sleep` so
        # the customer experience matches Windows. Backgrounded so the
        # caller returns quickly.
        wrapped = f"sleep {int(delay_s)}; osascript -e {repr(script)}"
        try:
            subprocess.Popen(["sh", "-c", wrapped + " &"])
            return True, f"scheduled in {delay_s}s"
        except Exception as e:
            return False, f"spawn failed: {e}"
    try:
        completed = subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
        if completed.returncode == 0:
            return True, "scheduled"
        return False, f"osascript rc={completed.returncode}: {completed.stderr.decode(errors='replace').strip()}"
    except FileNotFoundError:
        return False, "osascript not found"


def _power_linux(verb: str, delay_s: int, message: str) -> Tuple[bool, str]:
    """Linux power via systemctl / loginctl. Requires polkit rules for the
    current user — most distros allow `reboot`/`poweroff` for active session
    users out of the box; logout is always permitted."""
    import os as _os
    import subprocess

    if verb == "reboot":
        cmd = ["systemctl", "reboot"]
    elif verb == "shutdown":
        cmd = ["systemctl", "poweroff"]
    elif verb == "logoff":
        user = _os.environ.get("USER") or _os.environ.get("LOGNAME") or ""
        if not user:
            return False, "cannot determine current user"
        cmd = ["loginctl", "terminate-user", user]
    else:
        return False, f"unknown verb: {verb}"

    if delay_s > 0:
        wrapped = "sleep {} && {}".format(int(delay_s), " ".join(cmd))
        try:
            subprocess.Popen(["sh", "-c", wrapped + " &"])
            return True, f"scheduled in {delay_s}s"
        except Exception as e:
            return False, f"spawn failed: {e}"
    try:
        completed = subprocess.run(cmd, capture_output=True, timeout=10)
        if completed.returncode == 0:
            return True, "scheduled"
        return False, f"{cmd[0]} rc={completed.returncode}: {completed.stderr.decode(errors='replace').strip()}"
    except FileNotFoundError:
        return False, f"{cmd[0]} not found"


def power_action(verb: str, delay_s: int = 30, message: str = "") -> Tuple[bool, str]:
    """Schedule reboot/shutdown/logoff on the host OS. Verbs:
       reboot, shutdown, logoff
    `delay_s` is honored on Windows natively and emulated via `sleep`
    elsewhere. Returns (ok, detail) like the other control.* helpers."""
    if "windows" in OS:
        return _power_windows(verb, max(0, int(delay_s)), message or "RemoteConnect")
    if "darwin" in OS:
        return _power_macos(verb, max(0, int(delay_s)), message or "RemoteConnect")
    return _power_linux(verb, max(0, int(delay_s)), message or "RemoteConnect")


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
