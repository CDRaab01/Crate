# Crate deploy (self-hosted runner, tailnet-only)

Operational model cloned from Cookbook/Spotter (see their `deploy/README.md` for the
long-form runner guide). Crate-specific facts:

- **Host ports:** API `127.0.0.1:8005`, Postgres `127.0.0.1:5436`.
- **No tunnel.** Crate is tailnet-only: expose it with Tailscale Serve on the host
  (planned Serve port **8446** — 443/8443/8445 are taken by Magpie/Hawksnest/Remnant).
  Record the final ts.net URL in CLAUDE.md + ARCHITECTURE.md, point the eBay RuName's
  accept URL at `https://<ts.net>:8446/ebay/callback`, and set `CRATE_SERVER_URL`
  (GitHub Actions variable) so CI builds bake the right default server URL.
- **Runner:** register a self-hosted runner with the `crate` label; set the `CRATE_DIR`
  Actions variable to the canonical clone path. `deploy/redeploy.ps1` is the single
  redeploy entrypoint (fetch → reset → compose up → /health gate on 8005 → prune).
- **Secrets (server/.env on the host, never in the repo):** `SECRET_KEY`, eBay keyset +
  RuName + business-policy ids, `FERNET_KEY`, `SHIPPO_API_KEY` + `SHIP_FROM_*`. The
  crate-smoke client secret (`CRATE_SMOKE_CLIENT_SECRET`) must match the `crate-smoke`
  entry in dragonfly-id's `SMOKE_CLIENTS`.
- **Non-secret config pinned in `docker-compose.yml` `environment:`** (suite rule —
  Compose doesn't re-read env_file on recreate): `SUITE_JWKS_URL`, `SUITE_ISSUER`,
  `NTFY_BASE_URL`/`NTFY_TOPIC`.
- **Post-deploy smoke:** `scripts/synthetic_smoke.py` runs inside the container —
  dragonfly-id `/smoke/token` (crate-smoke, allowlisted subject
  `crate-smoke@dragonflymedia.org`) → `/auth/suite` → `/users/me`.
- **Volumes that must survive redeploys:** `pgdata` (Postgres) and `photos`
  (`/data/photos` — item photo binaries; the DB stores paths only).
