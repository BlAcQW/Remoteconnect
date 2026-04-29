#!/usr/bin/env bash
# Build a single-file Linux agent binary using PyInstaller.
#
# Output: agent/install/build/dist/linux/RemoteConnectAgent-linux-x86_64
#
# Usage:
#   ./build-linux.sh
#
# CI / signing: Linux binaries don't use code signing; this script just
# produces the binary and exits.
set -euo pipefail

cd "$(dirname "$0")"/../../..  # repo root
ROOT="$(pwd)"

OUT_DIR="${ROOT}/agent/install/build/dist/linux"
WORK_DIR="${ROOT}/agent/install/build/.work-linux"
ENTRY="${ROOT}/agent/install/build/agent_entry.py"

mkdir -p "${OUT_DIR}"

# Build venv with PyInstaller + agent deps
if [ ! -d "${WORK_DIR}/venv" ]; then
  python3 -m venv "${WORK_DIR}/venv"
  "${WORK_DIR}/venv/bin/pip" install --quiet --upgrade pip
  "${WORK_DIR}/venv/bin/pip" install --quiet -r "${ROOT}/agent/requirements.txt"
  "${WORK_DIR}/venv/bin/pip" install --quiet "pyinstaller>=6.15.0"
fi

# Build with PyInstaller
"${WORK_DIR}/venv/bin/pyinstaller" \
  --onefile \
  --name RemoteConnectAgent-linux-x86_64 \
  --distpath "${OUT_DIR}" \
  --workpath "${WORK_DIR}/build" \
  --specpath "${WORK_DIR}" \
  --add-data "${ROOT}/agent:agent" \
  --hidden-import agent \
  --hidden-import agent.agent \
  --hidden-import agent.config \
  --hidden-import agent.control \
  --hidden-import agent.input_handler \
  --hidden-import agent.screen_capture \
  --hidden-import agent.transfer_handlers \
  --hidden-import agent.runtime_state \
  --hidden-import agent.publisher_daily \
  --hidden-import websockets \
  --hidden-import httpx \
  --hidden-import dotenv \
  "${ENTRY}"

echo
echo "✓ Linux binary built at: ${OUT_DIR}/RemoteConnectAgent-linux-x86_64"
ls -lh "${OUT_DIR}/RemoteConnectAgent-linux-x86_64"
