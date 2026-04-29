#!/usr/bin/env bash
# RemoteConnect dev launcher — starts backend, frontend, and agent locally
# with hot reload. First run sets up venvs and installs deps; subsequent
# runs are fast.
#
# Usage:
#   ./dev.sh               start everything
#   ./dev.sh --no-agent    backend + frontend only (useful when developing
#                          the server without a local agent)
#   ./dev.sh setup         run idempotent setup only and exit
#
# Requirements: Python 3.12+, Node 18+, npm

set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"

# ── Colours / log helpers ────────────────────────────────────────────────
if [ -t 1 ]; then
  C_RED='\033[31m'; C_GRN='\033[32m'; C_YEL='\033[33m'; C_BLU='\033[34m'; C_DIM='\033[2m'; C_OFF='\033[0m'
else
  C_RED=''; C_GRN=''; C_YEL=''; C_BLU=''; C_DIM=''; C_OFF=''
fi
say()   { printf "${C_BLU}[dev]${C_OFF} %s\n" "$*"; }
warn()  { printf "${C_YEL}[dev]${C_OFF} %s\n" "$*" >&2; }
fail()  { printf "${C_RED}[dev]${C_OFF} %s\n" "$*" >&2; exit 1; }

# ── Sanity checks ────────────────────────────────────────────────────────
need_cmd() { command -v "$1" >/dev/null 2>&1 || fail "missing '$1' on PATH — install it before running ./dev.sh"; }
need_cmd python3
need_cmd npm
need_cmd node

PY_OK=$(python3 -c 'import sys; print(1 if sys.version_info>=(3,12) else 0)' 2>/dev/null || echo 0)
[ "$PY_OK" = "1" ] || fail "Python 3.12+ required (have: $(python3 --version 2>&1))"

NODE_MAJ=$(node -p "process.versions.node.split('.')[0]" 2>/dev/null || echo 0)
[ "${NODE_MAJ:-0}" -ge 18 ] || fail "Node 18+ required (have: $(node --version 2>&1))"

# ── Idempotent setup ─────────────────────────────────────────────────────
setup_backend() {
  if [ ! -d backend/venv ]; then
    say "creating backend/venv"
    python3 -m venv backend/venv
    backend/venv/bin/pip install --quiet --upgrade pip
    say "installing backend requirements (this may take a minute)"
    backend/venv/bin/pip install --quiet -r backend/requirements.txt
  fi
  if [ ! -f backend/.env ]; then
    say "generating backend/.env from .env.example"
    secret=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
    sed "s|change-me-to-a-long-random-secret-min-32-chars|$secret|" backend/.env.example > backend/.env
  fi
}

setup_agent() {
  if [ ! -d agent/venv ]; then
    say "creating agent/venv"
    python3 -m venv agent/venv
    agent/venv/bin/pip install --quiet --upgrade pip
    say "installing agent requirements (skipping daily-python — install separately if needed)"
    grep -v '^daily-python' agent/requirements.txt > /tmp/rc-agent-reqs.txt
    agent/venv/bin/pip install --quiet -r /tmp/rc-agent-reqs.txt
    rm -f /tmp/rc-agent-reqs.txt
    warn "daily-python not installed by default (native build, optional). To enable real video publish:"
    warn "  agent/venv/bin/pip install daily-python"
  fi
  if [ ! -f agent/.env ]; then
    say "copying agent/.env from .env.example"
    cp agent/.env.example agent/.env
  fi
}

setup_frontend() {
  if [ ! -d frontend/node_modules ]; then
    say "running npm install in frontend/"
    (cd frontend && npm install --no-audit --no-fund --silent)
  fi
  if [ ! -f frontend/.env.local ]; then
    say "copying frontend/.env.local from .env.example"
    cp frontend/.env.example frontend/.env.local
  fi
}

setup_all() {
  setup_backend
  setup_agent
  setup_frontend
  say "setup complete"
}

# ── Argument handling ────────────────────────────────────────────────────
WITH_AGENT=1
case "${1:-}" in
  setup)        setup_all; exit 0 ;;
  --no-agent)   WITH_AGENT=0 ;;
  ""|--with-agent) ;;
  -h|--help)
    cat <<EOF
Usage: $0 [setup|--no-agent|--with-agent]
  setup         install deps and exit
  --no-agent    start backend + frontend only
  (default)     start backend + frontend + agent
EOF
    exit 0
    ;;
  *) fail "unknown argument: $1 (try --help)" ;;
esac

setup_all

# ── Run with cleanup on exit ─────────────────────────────────────────────
PIDS=()
cleanup() {
  trap - INT TERM EXIT
  if [ ${#PIDS[@]} -gt 0 ]; then
    say "stopping (${#PIDS[@]} children)…"
    kill "${PIDS[@]}" 2>/dev/null || true
    wait "${PIDS[@]}" 2>/dev/null || true
  fi
}
trap cleanup INT TERM EXIT

prefix() {
  local tag="$1" col="$2"
  while IFS= read -r line; do
    printf "${col}[${tag}]${C_OFF} %s\n" "$line"
  done
}

start_backend() {
  say "starting backend on http://127.0.0.1:8765 (uvicorn --reload)"
  ( cd "$ROOT" && exec ./backend/venv/bin/uvicorn backend.main:app \
      --host 127.0.0.1 --port 8765 --reload \
  ) 2>&1 | prefix backend  "$C_GRN" &
  PIDS+=($!)
}

start_frontend() {
  say "starting frontend on http://localhost:3000 (next dev)"
  ( cd "$ROOT/frontend" && PORT=3000 exec npm run dev \
  ) 2>&1 | prefix frontend "$C_BLU" &
  PIDS+=($!)
}

start_agent() {
  say "starting agent (will register against http://127.0.0.1:8765)"
  ( cd "$ROOT" && exec ./agent/venv/bin/python -m agent.agent \
  ) 2>&1 | prefix agent    "$C_YEL" &
  PIDS+=($!)
}

start_backend
sleep 1
start_frontend
if [ "$WITH_AGENT" = "1" ]; then
  sleep 2  # give the backend a moment so the agent's first heartbeat doesn't 404
  start_agent
fi

cat <<EOF

${C_GRN}RemoteConnect dev stack is up.${C_OFF}
  Frontend: http://localhost:3000
  Backend:  http://127.0.0.1:8765   (proxied through frontend's /api/*)
  Logs:     in this terminal, prefixed [backend]/[frontend]/[agent]

  Sign in: register a new admin from the Login page (a demo user
  already exists in the Neon DB if you reused that backend/.env).

Ctrl-C to stop everything.

EOF

# Block until any child exits, then propagate.
wait -n 2>/dev/null || true
cleanup
