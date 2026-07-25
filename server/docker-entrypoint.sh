#!/usr/bin/env bash
#
# Container entrypoint: apply migrations, then run uvicorn. App config comes from
# environment variables (injected by compose via env_file + environment).
set -euo pipefail

echo "Applying database migrations…"
alembic upgrade head

args=(app.main:app --host 0.0.0.0 --port "${PORT:-8000}")
# Honour forwarded client IPs when behind a trusted proxy.
if [[ "${TRUST_PROXY:-}" == "true" ]]; then
  args+=(--proxy-headers --forwarded-allow-ips='*')
fi

echo "Starting Crate API…"
exec uvicorn "${args[@]}"
