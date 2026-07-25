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

## Capture pipeline (Phase 2, as built — server half)

`POST /items/scan` (20/min, multipart, 1-8 photos of ONE item, JPEG/PNG/WebP, 8 MB cap)
creates the draft + photo rows immediately (202) and hands the id to a background task;
the review stack polls `GET /items/{id}` until `processed_at` is set. The pipeline
(`services/scan_pipeline.py`, own DB session, CPU work on threads):

1. **Cleanup** (`services/cleanup.py`): rembg U2-Net background removal → white
   replacement → crop-to-subject (+6% margin) → 1% autocontrast → PNG on the photos
   volume. rembg missing/failed/disabled ⇒ Pillow-only pass — cleanup never blocks a
   draft. U2-Net weights are baked into the Docker image.
2. **Identify** (`services/ai/vision.py` + `identify_prompts.py`): up to 3 cleaned photos
   → LM Studio (strict-JSON prompt, fence-strip + widest-object-span salvage, condition
   normalized to the enum, weight/dims bounds-checked, title clamped to eBay's 80).
   Content failure ⇒ low-confidence empty draft (`scan_error="low_confidence"`);
   transport failure ⇒ `scan_error="identify_unavailable: …"` — the draft always
   survives with its photos.

Review surface: `GET /items[?status_filter=]`, `PATCH /items/{id}` (suite clearing
convention: null/omitted = untouched, "" = clear — `exclude_none`, because kotlinx
clients encode absent fields as explicit nulls), `DELETE /items/{id}` (draft/delisted
only — live listings must be delisted first), `GET /items/{id}/photos/{pid}/file`
(authenticated photo binary — cleaned when available), `GET /items/{id}/price-events`.
All owner-scoped.

**Client half:** camera/gallery shots (downscaled ≤1600px via `util/ImageBytes`) persist
to `filesDir/capture_queue/{id}/` + a Room row (`capture_queue`), drained by a
WorkManager `UploadWorker` (CONNECTED constraint, exponential backoff). Drain rules are
the suite's sync lessons: IOException ⇒ still pending, retry later; HttpException ⇒
mark `failed` for the user and KEEP DRAINING (no poison rows). The review stack
(`ui/review/`) lists server drafts, re-polls while any is processing, edits via the
PATCH convention, dismisses via DELETE. Coil rides the app's OkHttp client so photo
loads carry auth + the host rewrite.

## Shipping (Phase 7, as built — Shippo test mode, mocked in CI)

- **The confirm gate** (locked decision): `POST /items/{id}/confirm-weight` stores the
  human-checked weight/dims (`weight_confirmed=true`); `GET /items/{id}/rates` 409s
  until then — rates are quoted only against confirmed numbers because wrong-weight
  labels cost real money.
- **Rates** (`services/shippo.py`): one synchronous Shippo shipment per quote
  (ship-from from `SHIP_FROM_*` env, buyer address from the sale row, parcel from the
  confirmed numbers); the endpoint sorts per `user_settings.shipping_preference`
  (cheapest = amount; fastest = estimated_days then amount). Unconfigured ⇒ 503
  (Spoonacular precedent).
- **Label purchase** (`POST /items/{id}/buy-label`, REAL MONEY, explicit tap only,
  double-buy blocked by ship_status): Shippo transaction (SUCCESS-checked) → sale row
  gets tracking/label_url + the QUOTED carrier/service/cost (the transaction echoes
  the rate only as an id, so the client sends the picked quote back) → tracking pushed
  to the eBay order (`fulfillment.push_tracking`, GET order for lineItemIds →
  createShippingFulfillment) → lifecycle sold→shipped + ntfy. A failed tracking push
  logs + warns in the ntfy note but never loses the bought label.
- Client: Ship screen (pre-filled editable weight/dims → confirm → sorted rate cards →
  Buy → label PDF open), reached from the sold item's Sale card.

## Sale detection + buyer messages + ntfy (Phase 6, as built)

- **Poller** (`services/poller.py`, started from the app lifespan): every
  `POLL_INTERVAL_MINUTES` (15; 0 disables — CI/tests), for each connected user, pull
  orders (Fulfillment API, last 7 days) and buyer-message headers (Trading
  GetMyMessages, ReturnHeaders — subjects only in v1: Crate flags, it doesn't chat).
  One user's failure logs and never kills the loop. Polls OUT only — no inbound
  webhooks, consistent with tailnet-only.
- **Idempotency contracts:** `sales.ebay_order_id` and `buyer_messages.ebay_message_id`
  are unique — re-seeing the same order/message forever never duplicates. A new sale
  stores the minimum buyer payload needed to ship (name/address/phone), drives
  active→sold through the lifecycle service (which mints the duplicate template), and
  pings ntfy (high priority).
- **ntfy** (`services/notify.py`): silently off when unset (compose-pinned
  NTFY_BASE_URL/NTFY_TOPIC), best-effort — a dead push service never breaks a poll.
  Per-user topic override from `user_settings`.
- Surfaces: `GET /messages` (+ `unresolved_only`), `POST /messages/{id}/resolve`,
  `GET /items/{id}/sale` (buyer address + ship state for the Ship screen).
- Client: Inbox screen (flag list, resolve; replies happen in the eBay app), sold-state
  Sale card on item detail.

## eBay OAuth + posting (Phase 5, as built — sandbox-ready, mocked in CI)

- **Seller OAuth** (`services/ebay/oauth.py`): GET `/ebay/connect` (auth) returns the
  consent URL; the browser lands on eBay; eBay redirects to the unauthenticated
  `/ebay/callback` where a one-time in-process `state` (10-min TTL — single-user app,
  deliberate) proves the session and the code is exchanged. Tokens persist in
  `ebay_credentials` **Fernet-encrypted** (`FERNET_KEY` unset ⇒ connect 503s — tokens
  are never stored plaintext). `user_token()` auto-refreshes within 5 min of expiry and
  409s with "reconnect" when the ~18-month refresh token is dead; `/ebay/status`
  surfaces expiry for Settings.
- **Posting** (`services/ebay/sell.py`, POST `/items/{id}/post` — the explicit approve
  tap, never unattended): ensure ship-from location → **EPS photo upload via Trading
  API UploadSiteHostedPictures** (Crate is tailnet-only, eBay can't fetch our URLs, so
  binaries are pushed; EPS URLs cached on photo rows) → inventory item (sku = item id,
  Brand/Model aspects, condition mapped to the Inventory enum) → fixed-price offer
  (business-policy ids from env; 409 with instructions until the one-time seller setup
  exists) → publish → `ebay_listing_id` stored + lifecycle draft→active.
  POST `/items/{id}/delist` withdraws the offer (active→delisted).
  `update_offer_price()` exists for manual edits + the Phase 8 drop scheduler.
- Honest error surfaces: 503 keyset unconfigured / 409 not-connected or policies
  missing / 502 eBay rejected (with eBay's message excerpt).
- Client: Settings screen (connection status + one-time consent via browser + sign
  out); review cards gain "Post to eBay" (enabled only with title + chosen price).

## Pricing research (Phase 4, as built)

- `app/pricing/comps.py` — the pure math, the ONLY source of price numbers: IQR (1.5×)
  outlier trim (skipped under 4 comps), **patient = median of trimmed actives**,
  **quick-sale = min(cheapest_trimmed × 0.95, patient)**, $1 floor, cent-quantized.
  Active-market framing is deliberate and labeled in the UI: sold-comp data
  (Marketplace Insights) is partner-only.
- `app/pricing/browse.py` — Browse API client on an APPLICATION token
  (client-credentials, cached; needs no user consent so pricing works the moment a
  keyset exists, independent of Phase 5 seller OAuth). Sandbox/production host from
  `ebay_environment`; our condition enum maps to eBay conditionId buckets. Always
  mocked in CI.
- `app/pricing/service.py` — orchestration: query = brand+model (falls back to title),
  `price_item()` is best-effort in the scan pipeline (unconfigured keyset or eBay
  outage ⇒ a draft without prices, never a dead draft).
- `GET /items/{id}/comps` (30/min) — live evidence for the review screen (top 10 actives
  with links + both computed numbers); 503 until a keyset exists, 502 on eBay failure.
- Client: the review card gains the strategy picker (Quick $x / Patient $y / Custom →
  `chosen_price` via the normal PATCH) and honest "active-market, not solds" labeling.

## Registry + duplicate templates (Phase 3, as built — server half)

- `app/matching/signature.py` — the pure signature module: casefolded, deduped,
  order-stable brand+model tokens ("rapala f11"). **Deviation from the §4 sketch:
  category tokens are excluded** — the vision `category_hint` is transient, so a
  sale-time signature could never reproduce a capture-time one; brand+model is the
  natural "same lure model sold before" key. No brand AND no model ⇒ no signature ⇒
  never templated.
- `app/services/item_lifecycle.py` — the ONE place status transitions live
  (draft→active→sold→shipped, returned/delisted branches; illegal moves raise).
  `active` stamps `date_listed`; **`sold` upserts the duplicate template** (proven
  title/description/category + last price, use_count++), which is exactly when a
  listing pattern becomes worth reusing.
- Scan pipeline dup fast-path: after identification, a signature match prefills the
  draft from the template (template's proven copy wins; identification ran to confirm
  the match) and sets `template_id` — the client's "from template" badge.
- `GET /templates` / `DELETE /templates/{id}` (items keep template_id NULL via SET NULL).

## Data model (migration 0001 — the full CLAUDE.md §4 schema)

- `users` — id, email (unique), name, created_at. No password hash (SSO-only).
- `items` — the lifecycle row: identification fields all nullable (a fresh capture is just
  photos), status `draft|active|sold|shipped|returned|delisted` (transitions live in the
  item service only), two computed prices + chosen_price, eBay listing/offer ids,
  weight/dims estimate + weight_confirmed, template_id → duplicate_templates.
  Migration `0002` adds `brand`/`model` (they feed the Phase 3 template signature and must
  outlive the vision draft — an addition over the CLAUDE.md §4 sketch) and
  `processed_at`/`scan_error` (async scan-pipeline state).
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
