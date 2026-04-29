#!/usr/bin/env bash
# RemoteConnect agent — Linux installer.
#
# Installs the agent under the *current user's* home directory and
# registers it as a user-level systemd service. We deliberately do not run
# as root: pynput needs access to the active desktop session to inject
# input, and only the logged-in user has that.
#
# Usage:
#   ./install-linux.sh --server-url https://your.host
#   ./install-linux.sh --server-url https://your.host --name laptop-42
#   ./install-linux.sh --uninstall
#
# Optional flags:
#   --install-dir DIR     install location (default: ~/.local/share/remoteconnect-agent)
#   --no-start            don't enable/start the service
#   --enable-linger       systemctl loginctl enable-linger so the service
#                         runs even when the user isn't logged in

set -euo pipefail

INSTALL_DIR="${HOME}/.local/share/remoteconnect-agent"
SERVER_URL=""
SERVER_WS_URL=""
MACHINE_NAME=""
JOIN_TOKEN="${JOIN_TOKEN:-}"
ACTION="install"
START=1
LINGER=0

usage() {
  cat <<EOF
Usage: $0 [--server-url URL] [--name NAME] [--install-dir DIR] [--no-start] [--enable-linger]
       $0 --uninstall

  --server-url URL    backend, e.g. https://remoteconnect.example.com  (required for install)
  --ws-url URL        WS endpoint, defaults to http→ws / https→wss of --server-url
  --name NAME         machine display name (default: hostname)
  --install-dir DIR   install location (default: ${INSTALL_DIR})
  --no-start          install only; don't enable or start the service
  --enable-linger     run the service even when the user is logged out
  --join-token TOKEN  Quick Connect token (one-time; redeems on first
                      registration and pre-creates a technician session)
  --uninstall         stop, disable, and remove the agent
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --server-url)    SERVER_URL="$2"; shift 2 ;;
    --ws-url)        SERVER_WS_URL="$2"; shift 2 ;;
    --name)          MACHINE_NAME="$2"; shift 2 ;;
    --install-dir)   INSTALL_DIR="$2"; shift 2 ;;
    --join-token)    JOIN_TOKEN="$2"; shift 2 ;;
    --no-start)      START=0; shift ;;
    --enable-linger) LINGER=1; shift ;;
    --uninstall)     ACTION="uninstall"; shift ;;
    -h|--help)       usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage; exit 1 ;;
  esac
done

UNIT_DIR="${HOME}/.config/systemd/user"
UNIT_NAME="remoteconnect-agent.service"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_AGENT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"          # repo's agent/
SOURCE_REPO="$(cd "${SCRIPT_DIR}/../.." && pwd)"            # repo root

systemd_user() { systemctl --user "$@"; }

uninstall() {
  echo "Stopping ${UNIT_NAME}…"
  systemd_user stop "${UNIT_NAME}" 2>/dev/null || true
  systemd_user disable "${UNIT_NAME}" 2>/dev/null || true
  rm -f "${UNIT_DIR}/${UNIT_NAME}"
  systemd_user daemon-reload || true
  echo "Removing ${INSTALL_DIR}/"
  rm -rf "${INSTALL_DIR}"
  echo "Uninstalled."
}

install() {
  if [ -z "${SERVER_URL}" ]; then
    echo "--server-url is required for install" >&2
    usage; exit 2
  fi
  if [ -z "${SERVER_WS_URL}" ]; then
    case "${SERVER_URL}" in
      https://*) SERVER_WS_URL="wss://${SERVER_URL#https://}" ;;
      http://*)  SERVER_WS_URL="ws://${SERVER_URL#http://}" ;;
      *)         echo "--server-url must start with http:// or https://" >&2; exit 2 ;;
    esac
  fi
  if [ -z "${MACHINE_NAME}" ]; then
    MACHINE_NAME="$(hostname)"
  fi

  for cmd in python3 systemctl; do
    command -v "$cmd" >/dev/null 2>&1 || { echo "missing '$cmd' on PATH" >&2; exit 1; }
  done
  PY_OK=$(python3 -c 'import sys; print(1 if sys.version_info>=(3,12) else 0)' 2>/dev/null || echo 0)
  [ "$PY_OK" = "1" ] || { echo "Python 3.12+ required (have: $(python3 --version 2>&1))" >&2; exit 1; }

  echo "Installing RemoteConnect agent to ${INSTALL_DIR}"
  mkdir -p "${INSTALL_DIR}"

  echo "Copying agent source"
  rsync -a --delete \
        --exclude '__pycache__' --exclude 'venv' --exclude '.venv' \
        --exclude 'config.json' --exclude '.env' --exclude 'files' \
        "${SOURCE_AGENT_DIR}/" "${INSTALL_DIR}/agent/"

  # We need an importable `agent` package; create a tiny shim with __init__.py
  # so `python -m agent.agent` works from INSTALL_DIR as the working dir.
  touch "${INSTALL_DIR}/agent/__init__.py"

  echo "Creating venv"
  python3 -m venv "${INSTALL_DIR}/venv"
  "${INSTALL_DIR}/venv/bin/pip" install --quiet --upgrade pip
  echo "Installing agent dependencies (this may take a minute)"
  "${INSTALL_DIR}/venv/bin/pip" install --quiet -r "${INSTALL_DIR}/agent/requirements.txt" \
    || { echo "pip install failed — see output above" >&2; exit 1; }

  echo "Writing ${INSTALL_DIR}/agent/.env"
  cat > "${INSTALL_DIR}/agent/.env" <<EOF
SERVER_HTTP_URL=${SERVER_URL}
SERVER_WS_URL=${SERVER_WS_URL}
MACHINE_NAME=${MACHINE_NAME}
HEARTBEAT_INTERVAL_S=30
DAILY_PUBLISHER_CMD=
JOIN_TOKEN=${JOIN_TOKEN}
EOF

  mkdir -p "${UNIT_DIR}"
  echo "Writing ${UNIT_DIR}/${UNIT_NAME}"
  sed "s|__INSTALL_DIR__|${INSTALL_DIR}|g" \
      "${SCRIPT_DIR}/remoteconnect-agent.service.in" \
      > "${UNIT_DIR}/${UNIT_NAME}"

  systemd_user daemon-reload

  if [ "$LINGER" = "1" ]; then
    echo "Enabling user lingering (sudo required)"
    sudo loginctl enable-linger "$(id -un)"
  fi

  if [ "$START" = "1" ]; then
    echo "Enabling and starting ${UNIT_NAME}"
    systemd_user enable --now "${UNIT_NAME}"
    sleep 2
    systemd_user --no-pager status "${UNIT_NAME}" 2>&1 | head -10 || true
    cat <<EOF

Installed and started.
  Status:  systemctl --user status remoteconnect-agent
  Logs:    journalctl --user -u remoteconnect-agent -f
  Stop:    systemctl --user stop remoteconnect-agent
  Uninstall: ${SCRIPT_DIR}/install-linux.sh --uninstall
EOF
  else
    echo "Installed (not started). Run: systemctl --user enable --now ${UNIT_NAME}"
  fi
}

case "${ACTION}" in
  install)   install ;;
  uninstall) uninstall ;;
esac
