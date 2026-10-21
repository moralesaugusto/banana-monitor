# Running this project

Quick path to a working local instance. This is the fast local-dev version; a production-style install uses a systemd unit (`deploy/banana.service`), a dedicated user and a backed-up master key.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (manages the backend's Python version and virtualenv — no separate Python install needed)
- Node.js 20+ (build-time only; the built frontend is static files, Node isn't needed once it's built)

## Just run it

```
cp .env.example .env
python3 banana.py
```

That's it. `banana.py` installs the frontend's dependencies and builds `frontend/dist` only if its source changed since the last build (a no-op most of the time), then runs `uv run banana` — which syncs the backend virtualenv from `backend/uv.lock` and applies every pending database migration on its own. No separate `make venv`/`make build`/`make migrate` step, and safe to run again after every `git pull`.

Open **https://localhost:8000** (a self-signed certificate is generated on first run; your browser will ask you to accept it once). Sign in as **admin** with password **admin**; you are asked to choose a new password straight away (any non-empty password is accepted).

The defaults are fine for local use: the server binds `127.0.0.1`, data goes in `backend/data/`, and an encryption master key is generated automatically on first run (a warning is logged with its path; back that file up once it exists, and keep it out of backups of the data directory). `.env` holds only startup settings (`BANANA_*`); everything else (networks, integrations, credentials, Telegram, agents) is configured in the UI and stored in the databases.

**Ollama (optional, for the chat assistant and AI agents):** set `BANANA_OLLAMA_BASE_URL` and `BANANA_OLLAMA_MODEL` in `.env` before the first run if your Ollama is not on `localhost`. They only seed the initial settings; afterwards change them in the UI.

**Telegram (optional):** create a bot with @BotFather, paste its token under Settings > Telegram, message the bot, add the chat id it replies with, then enable it.

Skip to [Try it out](#try-it-out) below, or keep reading for the hot-reload development setup.

## Development setup (hot reload on the frontend)

Only needed if you're actively editing the frontend and want changes to show without a rebuild. Three one-time steps, then two terminals, all from the repo root:

```
make venv                    # once: uv sync in backend/
cd frontend && npm install   # once
cp .env.example .env         # once, if you haven't already
```

```
make dev-backend    # terminal 1: API on https://localhost:8000 (TLS 1.3 only; no autoreload - restart after backend changes)
```
```
make dev-frontend    # terminal 2: Vite dev server on http://localhost:5173, proxying /api to :8000
```

Open **http://localhost:5173** — that's the app, in dev mode with hot reload on the frontend. The backend already applies every pending migration on startup, so no separate `make migrate` step is needed here either (it still works by hand if you want to run migrations without starting the server: `make migrate`).

`make dev-backend` binds `127.0.0.1`. To reach it from other devices on your LAN run `make dev-backend BIND_HOST=0.0.0.0`; the dashboard has a login but is not hardened for exposure, so only do that on a network you trust.

Once you don't need frontend hot-reload, `make build && make run` (or just `python3 banana.py`, which does both) runs it as the single process it's designed to be in production — no autoreload, same codepath as `uv run banana`.

## Try it out

From the Integrations or Devices/Services pages (or via the API), add something to monitor:
- An **HTTP/TCP service**: any URL or host:port reachable from this machine — no credentials needed.
- A **Linux (SSH) integration**: point it at a host you can SSH into with a dedicated, restricted account.
- A **Proxmox VE integration**: needs a host, an API token ID, and the token secret as its credential.

Or use **Networks → Add network → Scan now** to discover devices/services on a LAN segment and review them on the **Discovery** page before they become monitored.

Define an **alert rule** (Alerts page) against something you're monitoring, then break it (stop the service, block the port) to watch it go `ok → pending → firing`, and fix it to watch it `resolve`.

## Running the test suite / checks

```
make check     # lint + tests, both backend and frontend
make test      # just tests
make lint      # just lint/type-check
```
