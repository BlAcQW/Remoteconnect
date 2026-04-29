#!/usr/bin/env bash
# Build a macOS agent app + .pkg using PyInstaller.
#
# Output: agent/install/build/dist/macos/RemoteConnectAgent-mac.app
#         agent/install/build/dist/macos/RemoteConnectAgent-mac.pkg
#
# If APPLE_DEVELOPER_ID and APPLE_TEAM_ID are set, signs and notarizes.
# Otherwise builds unsigned (Gatekeeper will block — user must
# right-click → Open → confirm).
set -euo pipefail

cd "$(dirname "$0")"/../../..
ROOT="$(pwd)"

OUT_DIR="${ROOT}/agent/install/build/dist/macos"
WORK_DIR="${ROOT}/agent/install/build/.work-macos"
ENTRY="${ROOT}/agent/install/build/agent_entry.py"

mkdir -p "${OUT_DIR}"

if [ ! -d "${WORK_DIR}/venv" ]; then
  python3 -m venv "${WORK_DIR}/venv"
  "${WORK_DIR}/venv/bin/pip" install --quiet --upgrade pip
  "${WORK_DIR}/venv/bin/pip" install --quiet -r "${ROOT}/agent/requirements.txt"
  "${WORK_DIR}/venv/bin/pip" install --quiet "pyinstaller>=6.15.0"
fi

"${WORK_DIR}/venv/bin/pyinstaller" \
  --onedir \
  --windowed \
  --name RemoteConnectAgent \
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

# Wrap into a .pkg (signed conditionally)
APP="${OUT_DIR}/RemoteConnectAgent.app"
PKG="${OUT_DIR}/RemoteConnectAgent-mac.pkg"
if command -v pkgbuild >/dev/null 2>&1; then
  pkgbuild --root "${OUT_DIR}/RemoteConnectAgent" \
           --identifier com.remoteconnect.agent \
           --version 1.0.0 \
           --install-location "/Applications/RemoteConnect" \
           "${PKG}"
fi

echo
echo "✓ macOS app: ${APP}"
[ -f "${PKG}" ] && echo "✓ macOS pkg: ${PKG}"

# Optional signing + notarization
"${ROOT}/agent/install/build/sign-macos.sh" "${APP}" "${PKG}" || true
