"""Helper tool state — search provider, pointer overlay tool, clipboard help.

The agent stores the current values and returns them on helper_state_get.
Provider and tool changes are acknowledged only; actual overlay rendering
happens on the viewer side inside the browser canvas. Clipboard help
enables/disables the clipboard sync loop.
"""
from __future__ import annotations

from typing import Literal

HelperProvider = Literal["google", "bing"]
HelperTool     = Literal["none", "lasso", "cross"]

_provider: HelperProvider = "google"
_tool: HelperTool         = "none"
_clipboard_help: bool     = False


def get_state() -> dict:
    return {
        "type":           "helper_state",
        "provider":       _provider,
        "tool":           _tool,
        "clipboard_help": _clipboard_help,
    }


def set_provider(p: str) -> None:
    global _provider
    if p in ("google", "bing"):
        _provider = p  # type: ignore[assignment]


def set_tool(t: str) -> None:
    global _tool
    if t in ("none", "lasso", "cross"):
        _tool = t  # type: ignore[assignment]


def set_clipboard_help(enabled: bool) -> bool:
    """Returns True if the value changed."""
    global _clipboard_help
    changed = _clipboard_help != enabled
    _clipboard_help = enabled
    return changed
