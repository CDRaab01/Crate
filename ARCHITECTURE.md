# ARCHITECTURE.md — Crate (as built)

> Update this file in the same PR as any change that alters a module's responsibility,
> a layer boundary, an external contract, or the data model (suite rule).

## System shape

```
[Android app (Kotlin/Compose, com.crate)]  <-- HTTPS/REST (tailnet only) -->  [FastAPI server]
                                                                                   |
                                                    +------------------------------+---------------+
                                                    |               |              |               |
                                              [Postgres]      [LM Studio]     [eBay APIs]     [Shippo]
                                                                (vision)      (poll out only)  (labels)
```

- **One app, one backend** (suite rule). The server owns all external-service access;
  the client never talks to eBay/Shippo/LM Studio directly.
- **Tailnet-only:** the API is published on `127.0.0.1:8005` and reached via Tailscale
  Serve on the host — no cloudflared, no public hostname. eBay never calls in; Crate
  polls out on schedulers. Planned Serve port: **8446** (443/8443/8445 are taken by
  Magpie/Hawksnest/Remnant) — confirm and record the real ts.net URL at first deploy.
- **SSO-only auth** (Magpie pattern): `POST /auth/suite` trades a Dragonfly suite token
  for a Crate session; no register/password endpoints exist. Feature-flagged on
  `SUITE_JWKS_URL`/`SUITE_ISSUER`, both pinned in compose `environment:`.

## Server (`server/`)

FastAPI + SQLAlchemy 2.0 async + Alembic, Postgres 16. Layout mirrors Cookbook:
`app/routers|services|models|schemas`, pure business math in dedicated modules.

Phase 0 surface:
- `GET /health` — `{"status": "ok"}`, unauthenticated.
- `GET /version` — `{name, version, commit, built_at}`, unauthenticated;
  `GIT_SHA`/`BUILT_AT` stamped by `deploy/redeploy.ps1` at deploy time.

Cross-cutting: slowapi rate limiting keyed on the real client IP (`app/limiter.py`),
security-headers middleware, IntegrityError→409 / SQLSTATE-22→422 handlers, migrations
on container boot (`docker-entrypoint.sh` → `alembic upgrade head`).

Photo binaries will live on the `photos` Docker volume (`/data/photos`), never in the
DB (paths only).

## Android (`android/`)

Kotlin, Jetpack Compose, MVVM + repository, Hilt. Consumes `design.pulse:pulse-ui` via
composite build (`includeBuild("../../Pulse")` — sibling checkout; CI checks Pulse out
next to the repo). **Copper leads** (`PulseAccent.Copper`, registered in Pulse
2026-07-25); the app-semantic channel map lives in `ui/theme/CrateTheme.kt`:
copper = hero/listing lifecycle, green = sold/shipped, blue = pricing data,
amber = attention, violet = provenance.

Suite wiring already in place: `util/SuiteConfigReader` (reads
`content://com.dragonfly.suiteconfig/config/crate` in `App.onCreate`, falls back to
local prefs), `util/AppPreferences` (server URL), the AppAuth
`RedirectUriReceiverActivity` AppCompat theme override, and the committed stable
keystore (`app/crate-debug.keystore`) with the suite-key release path in `release.yml`.

## CI/CD

- `ci.yml` — server ruff + pytest (Postgres service, migrations first), Android unit
  tests + assembleDebug (Pulse checked out as sibling), gitleaks, weekly pip-audit.
- `release.yml` — signed release APK + `version.json` on any `android/**` push to
  `main`; epoch-minutes versionCode; apksigner guard pinned to the suite signer
  (`5a596c9e…`).
- `deploy.yml` — self-hosted `crate`-labeled runner redeploys green `main` via
  `deploy/redeploy.ps1` (health-gated on `127.0.0.1:8005/health`), then runs the
  synthetic smoke inside the container. Human-gated setup: runner registration +
  `CRATE_DIR` Actions variable + Tailscale Serve config.

## Suite registrations (done at Phase 0, in sibling repos)

- Pulse: `PulseAccent.Copper` (+ accent claim).
- Dragonfly: `AppRegistry` + manifest `<queries>` rows for `crate`/`com.crate`;
  status-dashboard `ServiceRegistry` entry deferred until the ts.net URL is real.
- dragonfly-id: static OIDC client `crate` (redirect `com.crate:/oauth2redirect`);
  `crate-smoke@dragonflymedia.org` in the `SMOKE_SUBJECT_EMAILS` compose pin (the
  `crate-smoke` SMOKE_CLIENTS credential is set in the deployed `.env` by the owner).

## Auth (Phase 1, as built)

`POST /auth/suite` (10/min) validates an RS256 Dragonfly suite token against the identity
server's JWKS (cached, refetch-on-unknown-kid), find-or-creates the local user **by email**
(no password column exists anywhere — SSO-only), seeds the per-user `user_settings` row,
and returns Crate's own HS256 access/refresh pair. `POST /auth/refresh` (10/min) rotates
the pair; `GET /users/me` is the authenticated identity read. Everything lives in
`app/services/suite_auth.py` + `app/security.py`; unset `SUITE_JWKS_URL`/`SUITE_ISSUER` ⇒
404 (no login path — the flags are compose-pinned in production).
`scripts/synthetic_smoke.py` is the deploy gate: dragonfly-id `/smoke/token`
(crate-smoke credential) → `/auth/suite` → `/users/me`.

## Data model (migration 0001 — the full CLAUDE.md §4 schema)

- `users` — id, email (unique), name, created_at. No password hash (SSO-only).
- `items` — the lifecycle row: identification fields all nullable (a fresh capture is just
  photos), status `draft|active|sold|shipped|returned|delisted` (transitions live in the
  item service only), two computed prices + chosen_price, eBay listing/offer ids,
  weight/dims estimate + weight_confirmed, template_id → duplicate_templates.
- `item_photos` — ordered per item; original_path/cleaned_path on the photos volume
  (DB stores paths only), ebay_url after EPS upload. Cascade with the item.
- `sales` — one per eBay order (ebay_order_id unique): price/fees/date/buyer + address
  JSON, ship_status `pending|label_bought|shipped|delivered`, tracking/carrier/label.
- `buyer_messages` — flagged inbox rows (item nullable — pre-sale questions), unique
  ebay_message_id for poller idempotency.
- `duplicate_templates` — normalized-text signature (brand+model+category tokens, not
  embeddings) + reusable title/description/category, use_count/last_used.
- `price_events` — audit trail for every drop (auto_drop|manual|floor_reached).
- `ebay_credentials` — one row per user; access/refresh tokens stored encrypted
  (Fernet, Phase 5), sandbox|production environment tag.
- `user_settings` — the drop policy (enabled/interval/step), shipping preference,
  ntfy topic override; seeded at first login.
