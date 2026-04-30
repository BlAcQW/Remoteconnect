#!/usr/bin/env bash
# Build a macOS agent app + .pkg using PyInstaller.
#
# Output: agent/install/build/dist/macos/RemoteConnectAgent-mac.app
#         agent/install/build/dist/macos/RemoteConnectAgent-mac.pkg
#
# The production server URL is baked into the bundled binary so the .pkg
# can be installed without configuration. Override per-build via env vars:
#   SERVER_HTTP_URL=https://staging.example.com ./build-macos.sh
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

# Production endpoints baked into the bundle's .env. Override at build
# time with environment variables when producing dev/staging builds.
SERVER_HTTP_URL="${SERVER_HTTP_URL:-https://remoteconnect.ikieguy.online}"
case "${SERVER_HTTP_URL}" in
  https://*) SERVER_WS_URL="${SERVER_WS_URL:-wss://${SERVER_HTTP_URL#https://}}" ;;
  http://*)  SERVER_WS_URL="${SERVER_WS_URL:-ws://${SERVER_HTTP_URL#http://}}"   ;;
  *) echo "SERVER_HTTP_URL must start with http:// or https:// (got: ${SERVER_HTTP_URL})" >&2; exit 1 ;;
esac
echo "Building with SERVER_HTTP_URL=${SERVER_HTTP_URL}"
echo "                SERVER_WS_URL=${SERVER_WS_URL}"

mkdir -p "${OUT_DIR}"

# Stage a clean copy of agent/ for bundling. Strips dev artifacts and
# writes the production .env so the binary self-configures on first run.
AGENT_STAGE="${WORK_DIR}/agent-stage"
rm -rf "${AGENT_STAGE}"
mkdir -p "${AGENT_STAGE}"
# rsync (not cp -R) because the work dir lives inside agent/, so a naive
# recursive copy would self-include and explode. Excluded paths cover dev
# artifacts and the installer build dir itself.
rsync -a \
  --exclude='install/build/.work-*' \
  --exclude='install/build/dist' \
  --exclude='venv/' --exclude='.venv/' \
  --exclude='__pycache__/' \
  --exclude='config.json' --exclude='.env' \
  --exclude='files/' \
  "${ROOT}/agent/" "${AGENT_STAGE}/"
cat > "${AGENT_STAGE}/.env" <<EOF
SERVER_HTTP_URL=${SERVER_HTTP_URL}
SERVER_WS_URL=${SERVER_WS_URL}
HEARTBEAT_INTERVAL_S=30
DAILY_PUBLISHER_CMD=
EOF

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
  --add-data "${AGENT_STAGE}:agent" \
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
