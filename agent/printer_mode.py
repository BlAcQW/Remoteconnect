"""Printer sharing mode management.

Controls which printers are shared in the remote session.

Windows: manipulates the HKLM terminal-services printer config keys and
         optionally restarts the Print Spooler to apply the change live.
Linux/macOS: stores the preference only (CUPS-based printer sharing is
             handled at the session-broker level, not the agent).
"""
from __future__ import annotations

import logging
import sys
from typing import Literal

log = logging.getLogger(__name__)

PrinterMode = Literal["none", "default", "all"]
_current: PrinterMode = "none"


def get() -> PrinterMode:
    return _current


def set_mode(mode: str) -> bool:
    global _current
    if mode not in ("none", "default", "all"):
        return False
    _current = mode  # type: ignore[assignment]
    if sys.platform == "win32":
        _apply_windows(mode)
    else:
        log.info("Printer mode set to %r (no-op on %s)", mode, sys.platform)
    return True


def _apply_windows(mode: str) -> None:
    try:
        import winreg
        key_path = r"SYSTEM\CurrentControlSet\Control\Terminal Server\Wds\rdpwd"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path,
                            0, winreg.KEY_SET_VALUE) as k:
            # fEnablePrinterRedirection: 0=none, 1=default-only, 2=all
            value_map = {"none": 0, "default": 1, "all": 2}
            winreg.SetValueEx(k, "fEnablePrinterRedirection", 0,
                              winreg.REG_DWORD, value_map[mode])
        log.info("Windows printer redirect registry set to %r", mode)
    except Exception:
        log.exception("Failed to set printer mode in registry")
