"""PyInstaller entrypoint with installer-style GUI wrapper.

When the customer runs the bundled binary, this entry:
  1. Pops a small dark-themed window that looks like an installer
     (title, subtitle, animated status line). Hides the cmd window
     entirely on Windows when built with --noconsole.
  2. Runs the agent's asyncio event loop in a background thread.
  3. Watches the agent's logger and reflects key transitions
     ("Registering...", "Registered", "WebSocket connected") into
     the status label so the customer sees progress.
  4. Auto-hides the window AFTER_HIDE_DELAY_MS once the agent is
     connected. The Tk mainloop keeps running, so the daemon agent
     thread stays alive and the customer's machine remains reachable
     to the technician — they just don't see a window. The X button
     also withdraws (instead of destroying) for the same reason.
  5. On crash, surfaces a clean error dialog with the path to the
     log file rather than dumping a Python stack trace into a cmd
     window the customer will never know how to read.

NOTE: ``import asyncio`` is at module scope on purpose — this is what
tells PyInstaller's static analyzer to bundle the asyncio stdlib package.
A ``from agent.agent import asyncio`` (which is what the previous version
did) is interpreted as "fetch the asyncio attribute from agent.agent",
which does NOT trigger asyncio bundling and yields ``ModuleNotFoundError:
No module named 'asyncio'`` at runtime.
"""
from __future__ import annotations

import asyncio  # noqa: F401  — required for PyInstaller to bundle asyncio
import logging
import os
import sys
import tempfile
import threading
import tkinter as tk
import traceback
from tkinter import messagebox

LOG_PATH = os.path.join(tempfile.gettempdir(), "remoteconnect-agent.log")

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


# How long to keep the install window visible after the agent reports
# "Connected" before auto-hiding. Long enough that the customer can read
# the message, short enough that they're not staring at it.
AUTO_HIDE_DELAY_MS = 3000

# A status string to look for to know we're done installing. When the
# UI text matches this, schedule the auto-hide.
HIDE_STATUS_TRIGGER = "Connected — waiting for technician"


# Keywords in agent log lines → friendly UI status string.
# Order matters: first match wins.
STATUS_RULES: list[tuple[str, str]] = [
    ("Loaded existing credentials", "Resuming session"),
    ("Using Quick Connect token", "Activating invite"),
    ("Registering with", "Registering this computer"),
    ("Registered machine_id", "Registered with server"),
    ("WS connected", HIDE_STATUS_TRIGGER),
    ("WebSocket connected", HIDE_STATUS_TRIGGER),
    ("Heartbeat", HIDE_STATUS_TRIGGER),
    ("consent: session", "Technician requesting access"),
]


class InstallerWindow:
    """Minimal dark-themed window that masquerades as an installer.

    Once the agent reports "Connected" we withdraw (hide) the window after
    AUTO_HIDE_DELAY_MS. Tk mainloop keeps running so the daemon agent
    thread stays alive — closing the X also withdraws instead of destroys
    for the same reason. The agent process keeps running silently in the
    background until the user signs out / reboots / kills it via Task
    Manager.
    """

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("RemoteConnect Setup")
        self.root.geometry("440x240")
        self.root.resizable(False, False)
        try:
            self.root.attributes("-topmost", True)
            self.root.after(800, lambda: self.root.attributes("-topmost", False))
        except tk.TclError:
            pass
        self.root.configure(bg="#0e1117")
        self._hide_scheduled = False
        # Closing the X button: don't destroy — that would end the Tk
        # mainloop and kill the daemon agent thread along with it. Just
        # hide. The agent keeps running in the background.
        self.root.protocol("WM_DELETE_WINDOW", lambda: self.root.withdraw())

        tk.Label(
            self.root,
            text="RemoteConnect",
            font=("Segoe UI", 18, "bold"),
            fg="#ffffff",
            bg="#0e1117",
        ).pack(pady=(28, 4))

        tk.Label(
            self.root,
            text="Setting up secure remote support…",
            font=("Segoe UI", 10),
            fg="#9aa0a6",
            bg="#0e1117",
        ).pack()

        self._status_text = tk.StringVar(value="Connecting to server")
        tk.Label(
            self.root,
            textvariable=self._status_text,
            font=("Segoe UI", 11),
            fg="#4ea1ff",
            bg="#0e1117",
        ).pack(pady=(34, 6))

        self._detail_text = tk.StringVar(value="This window will stay open for the duration of the session.")
        tk.Label(
            self.root,
            textvariable=self._detail_text,
            font=("Segoe UI", 9),
            fg="#5f6368",
            bg="#0e1117",
            wraplength=400,
            justify="center",
        ).pack()

        self._dots = 0
        self._tick_dots()

    # animated trailing dots so the user feels something is happening
    def _tick_dots(self) -> None:
        self._dots = (self._dots + 1) % 4
        base = self._status_text.get().rstrip(".")
        self._status_text.set(base + ("." * self._dots))
        self.root.after(450, self._tick_dots)

    def set_status(self, message: str, detail: str | None = None) -> None:
        def _apply() -> None:
            self._status_text.set(message)
            if detail is not None:
                self._detail_text.set(detail)
            # Once we've reached the "Connected" milestone, schedule a
            # one-time auto-hide so the customer doesn't have to look at
            # the window all day. Subsequent status changes (consent
            # prompts etc.) won't reschedule it.
            if message == HIDE_STATUS_TRIGGER and not self._hide_scheduled:
                self._hide_scheduled = True
                self.root.after(AUTO_HIDE_DELAY_MS, self._hide)
        self.root.after(0, _apply)

    def _hide(self) -> None:
        try:
            self.root.withdraw()
        except tk.TclError:
            # Window already destroyed — fine.
            pass

    def show_error_and_close(self, message: str) -> None:
        def _apply() -> None:
            messagebox.showerror("RemoteConnect", message)
            self.root.destroy()
        self.root.after(0, _apply)

    def run(self) -> None:
        self.root.mainloop()


class GuiLogHandler(logging.Handler):
    """Listens to the agent's logger and updates the installer window."""

    def __init__(self, window: InstallerWindow) -> None:
        super().__init__(level=logging.INFO)
        self.window = window

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:
            return
        for needle, status in STATUS_RULES:
            if needle in msg:
                self.window.set_status(status, f"Logs: {LOG_PATH}")
                return


def _agent_thread(window: InstallerWindow) -> None:
    """Background worker: runs the agent's asyncio event loop."""
    try:
        # Importing here keeps Tk responsive during initial paint.
        from agent.agent import main as agent_main

        # Wire log → GUI status
        logging.getLogger("agent").addHandler(GuiLogHandler(window))
        logging.getLogger().addHandler(GuiLogHandler(window))

        window.set_status("Connecting to server", f"Logs: {LOG_PATH}")
        asyncio.run(agent_main())
    except Exception as exc:
        logging.exception("agent crashed")
        window.show_error_and_close(
            f"RemoteConnect failed to start.\n\n"
            f"{type(exc).__name__}: {exc}\n\n"
            f"Logs were saved to:\n{LOG_PATH}"
        )


def _run_console_only() -> int:
    """Headless fallback (no display, or REMOTECONNECT_NO_GUI=1)."""
    from agent.agent import main as agent_main

    asyncio.run(agent_main())
    return 0


def main() -> int:
    if os.getenv("REMOTECONNECT_NO_GUI"):
        return _run_console_only()
    try:
        window = InstallerWindow()
    except tk.TclError:
        # No display available (headless Linux, etc.) — run without UI.
        return _run_console_only()
    worker = threading.Thread(target=_agent_thread, args=(window,), daemon=True)
    worker.start()
    window.run()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Last-ditch: write any unhandled error so the user can find it.
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as fp:
                fp.write("\n=== unhandled top-level error ===\n")
                fp.write(traceback.format_exc())
        except OSError:
            pass
        sys.exit(1)
