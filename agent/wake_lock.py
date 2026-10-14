"""Wake-lock: prevent the remote machine from sleeping/screensaving.

Windows: SetThreadExecutionState with ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
Linux:   inhibit via org.freedesktop.PowerManagement D-Bus or systemd-inhibit subprocess
macOS:   IOPMAssertionCreateWithName via ctypes
"""
from __future__ import annotations

import logging
import subprocess
import sys

log = logging.getLogger(__name__)

_active = False
_win_cookie: int | None = None  # unused on Win, ES_CONTINUOUS handles teardown


def acquire() -> bool:
    global _active, _win_cookie
    if _active:
        return True
    try:
        if sys.platform == "win32":
            import ctypes
            ES_CONTINUOUS        = 0x80000000
            ES_SYSTEM_REQUIRED   = 0x00000001
            ES_DISPLAY_REQUIRED  = 0x00000002
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
            )
        elif sys.platform == "darwin":
            import ctypes, ctypes.util
            iokit = ctypes.cdll.LoadLibrary(ctypes.util.find_library("IOKit"))
            cf    = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
            kIOPMAssertionLevelOn = 255
            assertion_type  = cf.CFStringCreateWithCString(None, b"PreventUserIdleSystemSleep", 0)
            assertion_name  = cf.CFStringCreateWithCString(None, b"RemoteConnect wake lock", 0)
            assertion_id    = ctypes.c_uint32(0)
            iokit.IOPMAssertionCreateWithName(
                assertion_type, kIOPMAssertionLevelOn,
                assertion_name, ctypes.byref(assertion_id)
            )
            _win_cookie = assertion_id.value
        else:
            # Linux — try systemd-inhibit in background; ignore failure
            subprocess.Popen(
                ["systemd-inhibit", "--what=sleep:idle", "--who=RemoteConnect",
                 "--why=Active remote session", "--mode=block", "sleep", "infinity"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        _active = True
        log.info("Wake lock acquired")
        return True
    except Exception:
        log.exception("Failed to acquire wake lock")
        return False


def release() -> bool:
    global _active, _win_cookie
    if not _active:
        return True
    try:
        if sys.platform == "win32":
            import ctypes
            ES_CONTINUOUS = 0x80000000
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        elif sys.platform == "darwin" and _win_cookie is not None:
            import ctypes, ctypes.util
            iokit = ctypes.cdll.LoadLibrary(ctypes.util.find_library("IOKit"))
            iokit.IOPMAssertionRelease(_win_cookie)
            _win_cookie = None
        else:
            # Linux: the systemd-inhibit child holds the lock; killing it releases.
            subprocess.run(
                ["pkill", "-f", "systemd-inhibit.*RemoteConnect"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        _active = False
        log.info("Wake lock released")
        return True
    except Exception:
        log.exception("Failed to release wake lock")
        return False


def is_active() -> bool:
    return _active
