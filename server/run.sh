#!/usr/bin/env bash
#
# Start the Crate FastAPI server: ensures the virtualenv, applies database
# migrations, then runs uvicorn.
#
# App config is read from server/.env by pydantic-settings — see .env.example.
# This script only controls how the process is launched:
#
#   HOST     bind address   (default 127.0.0.1; use 0.0.0.0 for Tailscale/LAN access)
#   PORT     bind port       (default 8000)
#   RELOAD   set to 1 for auto-reload during development (default 0)
#
# Usage:
#   ./run.sh                      # local: http://127.0.0.1:8000
#   HOST=0.0.0.0 ./run.sh         # reachable on the LAN / tailnet
#   RELOAD=1 ./run.sh             # development with auto-reload
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "error: server/.env not found — copy the example and set SECRET_KEY:" >&2
  echo "  cp .env.example .env" >&2
  exit 1
fi

# Create the virtualenv and install deps on first run.
if [[ ! -x .venv/bin/uvicorn ]]; then
  echo "Setting up virtualenv (.venv)…"
  python3 -m venv .venv
  .venv/bin/pip install -q -e ".[dev]"
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

echo "Applying database migrations…"
.venv/bin/alembic upgrade head

uvicorn_args=(app.main:app --host "$HOST" --port "$PORT")
[[ "${RELOAD:-0}" == "1" ]] && uvicorn_args+=(--reload)
# Honour forwarded client IPs when behind a trusted proxy (matches TRUST_PROXY in .env).
if grep -qiE '^[[:space:]]*TRUST_PROXY[[:space:]]*=[[:space:]]*true' .env; then
  echo "TRUST_PROXY enabled — running with --proxy-headers."
  uvicorn_args+=(--proxy-headers --forwarded-allow-ips='*')
fi

echo "Starting Crate API on http://$HOST:$PORT"
exec .venv/bin/uvicorn "${uvicorn_args[@]}"
