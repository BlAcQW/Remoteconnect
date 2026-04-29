# RemoteConnect

A self-hosted remote support & access platform — technician browser console
that controls a remote machine through a Daily.co WebRTC bridge. Three
components:

- **`backend/`** — FastAPI + SQLAlchemy. Auth, machine registry, sessions,
  WebSocket signaling for both agents and technicians. SQLite by default,
  Postgres-ready (works with Neon, etc.) via `DATABASE_URL`.
- **`frontend/`** — Next.js 14 App Router. Login, dashboard with live
  machine list, session viewer with embedded Daily.co video, mouse/keyboard
  passthrough, and chunked file transfer.
- **`agent/`** — Python daemon that runs on the remote machine. Registers
  with the backend, holds an outbound WebSocket open, accepts input
  passthrough, can launch a Daily.co publisher to share its screen, and
  handles file uploads/downloads inside a sandboxed share dir.

> The PRD that drove the build is at [`prd.md`](./prd.md).

## Quickstart

```bash
git clone <repo>
cd remoteconnect
./dev.sh
```

First run takes ~30 seconds (creates two Python venvs, runs `npm install`).
Subsequent runs start in ~3 seconds.

Open <http://localhost:3000> → Sign in:

- If you reused an existing `backend/.env` (e.g. with a Neon `DATABASE_URL`)
  the demo user `admin2@example.com` / `pw12345` works.
- For a fresh SQLite database, register a new account from the login page.

## Project layout

```
remoteconnect/
├── dev.sh                    ← bootstrap + run all 3 services
├── docker-compose.yml        ← optional Docker path
├── backend/
│   ├── main.py               FastAPI app, CORS, lifespan
│   ├── database.py           SQLAlchemy engine (SQLite/Postgres auto-switch)
│   ├── models/               User, Machine, Session, FileTransfer
│   ├── routers/              auth, machines, sessions, signaling
│   ├── integrations/daily.py Daily.co REST client (with mock fallback)
│   ├── websocket_manager.py  agent + technician WS registries
│   └── requirements.txt
├── frontend/
│   ├── app/                  Next.js App Router
│   │   ├── (auth)/login/     Login page
│   │   ├── dashboard/        Machine list with SWR polling
│   │   ├── session/[id]/     Live viewer + file panel
│   │   └── api/              Server-side proxy to FastAPI (cookie-auth)
│   ├── components/session/   SessionViewer, RemoteToolbar, FilePanel,
│   │                         TechnicianChannel (shared WS)
│   ├── lib/                  client-api, server-api, types, keymap
│   └── package.json
└── agent/
    ├── agent.py              Main loop: register → heartbeat → WS dispatch
    ├── config.py             Env + persisted creds (config.json)
    ├── screen_capture.py     mss + Pillow JPEG (lazy-imported)
    ├── input_handler.py      pynput mouse/keyboard (lazy-imported)
    ├── transfer_handlers.py  Upload/download with sandboxed share dir
    ├── publisher_daily.py    Optional Daily SDK publisher
    └── requirements.txt
```

## Environment variables

Each component has its own `.env.example`. Copy → `.env` (or `.env.local`
for the frontend) and edit. `dev.sh` does this automatically on first run.

### `backend/.env`

| Var | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `` | SQLAlchemy URL. Postgres URLs are auto-rewritten to `postgresql+asyncpg://`; libpq query params (`sslmode`, `channel_binding`) are stripped and SSL is configured via `connect_args`. |
| `JWT_SECRET` | (required, 32+ chars) | Signs login tokens. `dev.sh` rolls a random one on first run. |
| `DAILY_API_KEY` | empty | When unset the backend uses mock Daily URLs/tokens. Set to a real key from <https://dashboard.daily.co/developers> to publish real video. |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowlist for the FastAPI app. The browser usually goes through the Next.js `/api/*` proxy, so this only matters for direct API consumers. |

### `frontend/.env.local`

| Var | Default | Purpose |
|---|---|---|
| `BACKEND_URL` | `` | Server-side only. Where Next.js Route Handlers proxy to. |
| `JWT_COOKIE_NAME` | `rc_jwt` | Cookie name for the technician JWT. |
| `JWT_COOKIE_MAX_AGE_S` | `86400` | 24h, matches backend `ACCESS_TOKEN_EXPIRE_MINUTES`. |
| `PORT` | `3000` (set by `dev.sh`) | Next.js listen port. |

### `agent/.env`

| Var | Default | Purpose |
|---|---|---|
| `SERVER_HTTP_URL` | ` | Backend HTTP for register/heartbeat. |
| `SERVER_WS_URL` | `` | Backend WS for command channel. Switch to `wss://` for production. |
| `MACHINE_NAME` | `socket.gethostname()` | Display name in the dashboard. |
| `HEARTBEAT_INTERVAL_S` | `30` | Heartbeat period. |
| `DAILY_PUBLISHER_CMD` | empty | Shell command run on `start_session` to publish the screen. Empty = log-only. See `agent/.env.example` for the recommended bundled publisher (`python -m agent.publisher_daily`). |
| `SHARED_DIR` | `agent/files/` | Sandbox for upload destinations and download sources. |

## Running each component manually

If `dev.sh` is too magical, here's what it does — run each in its own
terminal:

```bash
# Backend  (terminal 1)
cd remoteconnect
./backend/venv/bin/uvicorn backend.main:app --reload --host 127.0.0.1 --port 8765

# Frontend (terminal 2)
cd remoteconnect/frontend
PORT=3000 npm run dev

# Agent (terminal 3) — optional, only on machines you want to control
cd remoteconnect
./agent/venv/bin/python -m agent.agent
```

## Docker (optional)

For someone who doesn't want to install Python 3.12 + Node 24 locally:

```bash
docker compose up
```

Compose runs backend + frontend with hot-reload (source mounted). The agent
is not in compose — agents live on the machines you want to remote-control,
so you'd run them on those machines directly.



## Caveats

- **Tests are sparse.** Most verification was done end-to-end via curl + WS
  scripts during development. Adding pytest/Vitest coverage is a worthwhile
  next step before relying on this in production.
- **The agent's input passthrough (pynput) needs a real desktop session.**
  On a headless Linux box (no `DISPLAY`), the WS messages arrive at the
  right handlers but `pynput` errors out trying to acquire X. Run the agent
  on a real laptop/desktop or under `xvfb-run`.
- **Daily.co publishing requires real credentials.** Without `DAILY_API_KEY`
  set on the backend, the system uses mock room URLs — useful for testing
  the full message flow but no actual video is sent.
- **Single technician per session.** The backend uses last-writer-wins on
  the `/ws/technician/{session_id}` channel; a second login on the same
  session evicts the first.

## License

Not yet specified — add one before publishing.
