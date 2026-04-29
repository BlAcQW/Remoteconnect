import json
import os
import platform
import socket
from pathlib import Path
from typing import Optional, TypedDict

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

SERVER_HTTP_URL: str = os.getenv("SERVER_HTTP_URL", "http://127.0.0.1:8765")
SERVER_WS_URL: str = os.getenv("SERVER_WS_URL", "ws://127.0.0.1:8765")
MACHINE_NAME: str = os.getenv("MACHINE_NAME") or socket.gethostname()
HEARTBEAT_INTERVAL_S: int = int(os.getenv("HEARTBEAT_INTERVAL_S", "30"))

# Quick Connect: when set on first run, the agent passes this token in
# /machines/register so the backend redeems it and pre-creates a session
# for the technician who issued the invite.
JOIN_TOKEN: str = os.getenv("JOIN_TOKEN", "")

# Pluggable Daily.co publisher. Empty = log-only (default). When set, the
# agent runs this command (passed to /bin/sh -c) on `start_session` with the
# environment variables DAILY_ROOM_URL, DAILY_MEETING_TOKEN, DAILY_SESSION_ID
# populated. Example for headless Chromium screen-share:
#   chromium --headless=new --auto-select-desktop-capture-source=Screen \
#     --use-fake-ui-for-media-stream "$DAILY_ROOM_URL?t=$DAILY_MEETING_TOKEN"
DAILY_PUBLISHER_CMD: str = os.getenv("DAILY_PUBLISHER_CMD", "")

# Sandboxed directory for file-transfer uploads/downloads. Uploads land here;
# downloads must resolve to a path inside this directory.
SHARED_DIR: Path = Path(os.getenv("SHARED_DIR") or (Path(__file__).parent / "files")).expanduser().resolve()
SHARED_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_PATH: Path = Path(__file__).parent / "config.json"


class Credentials(TypedDict):
    machine_id: str
    token: str


def load_credentials() -> Optional[Credentials]:
    if not CONFIG_PATH.exists():
        return None
    data = json.loads(CONFIG_PATH.read_text())
    return Credentials(machine_id=data["machine_id"], token=data["token"])


def save_credentials(machine_id: str, token: str) -> None:
    CONFIG_PATH.write_text(json.dumps({"machine_id": machine_id, "token": token}, indent=2))


def detect_os() -> str:
    s = platform.system().lower()
    if "windows" in s:
        return "windows"
    if "darwin" in s:
        return "macos"
    return "linux"
