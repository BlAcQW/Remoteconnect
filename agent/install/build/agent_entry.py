"""PyInstaller entrypoint for the standalone agent binary.

When the customer runs the bundled binary, it:
  1. Reads JOIN_TOKEN, SERVER_HTTP_URL, SERVER_WS_URL from environment or
     from config.json (unset on first run — the customer arrives via
     a Quick Connect link that sets them).
  2. If a config.json doesn't exist yet AND a JOIN_TOKEN is provided, the
     agent registers, the backend redeems the token, and persists creds.
  3. Subsequent runs re-use the persisted creds.

For the Quick Connect flow, the server-side fallback installer wraps this
binary in a tiny script that sets JOIN_TOKEN env before launching it. Once
we have proper PyInstaller binaries shipping, the binary will read its
embedded JOIN_TOKEN from a build-time sidecar (TODO).
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    # Detect whether we're a frozen PyInstaller bundle vs running from source.
    # When frozen, the agent module is bundled inside; --onefile extracts to
    # a temp dir at sys._MEIPASS — both paths still work because the entry
    # imports the package normally.
    from agent.agent import main as agent_main, asyncio
    try:
        asyncio.run(agent_main())
        return 0
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
