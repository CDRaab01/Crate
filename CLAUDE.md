# CLAUDE.md — "Crate"

> Photo-to-shipped-package automation for eBay selling. Snap a picture, review an
> AI-generated listing with two price points, approve, and Crate handles posting,
> sale tracking, and shipping logistics. Sixth app in the personal suite alongside
> **Spotter** (fitness), **Plate** (nutrition), **Cookbook** (recipes/shopping),
> **Dragonfly** (hub/identity), and **Magpie**. Same stack, same conventions, same
> PULSE design language consumed as the shared `pulse-ui` library.

---

## 0. Read this first

This file is the source of truth for the build. Work **phase by phase** (§7); do not
start a later phase before the earlier one's exit criteria (tests green, CI green) are
met. When a decision is ambiguous, **match the existing suite apps' choice** — inspect
the sibling repos (Cookbook is the closest full-pipeline template; Magpie is the
SSO-only/tailnet-only template) and mirror their patterns. If this file conflicts with
how the existing apps actually do something, **the existing apps win** — flag the
conflict.

Before writing code in any phase: restate the phase goal, list the files you'll touch,
flag any assumption, then proceed.

**Decisions locked 2026-07-25 (user-confirmed):**

| Topic | Decision |
|---|---|
| Name / package | **Crate**, `com.crate`, repo `CDRaab01/Crate` |
| Pricing data | **Active comps only** (eBay Browse API). Sold-comp data (Marketplace Insights API) is partner-only and not obtainable — do not design against it. Quick-sale = undercut the cheapest credible active comp; patient = median of actives. |
| Shipping labels | **Shippo** (open API, free tier, test mode). eBay's own Logistics API is restricted-access — not used. Tracking is pushed back to the eBay order via the Fulfillment API. |
| Storage | **Postgres** + SQLAlchemy 2.0 async + Alembic (suite standard; supersedes the early SQLite sketch). Host ports **8007 (API) / 5438 (Postgres)** (8005/5436 turned out to be Magpie's — corrected at first deploy). |
| eBay account | None exists yet → **sandbox-first sequencing**; eBay always mocked in CI; production keyset + OAuth consent are human-gated items. |
| Auth | **SSO-only** (Magpie precedent): "Sign in with Dragonfly" via `POST /auth/suite`, no register/password endpoints, synthetic-smoke token for deploy smokes. |
| Reachability | **Tailnet-only** (Magpie pattern) — ts.net URL, no cloudflared/public hostname. Crate only polls out; eBay never calls in. |
| Photo cleanup | **Full in v1**: `rembg` (local U2-Net, CPU) background removal + white replacement, plus Pillow crop/straighten/levels — all server-side. |
| Price drops | **Automatic with notify**: −10% every 14 days, floor at the quick-sale price, ntfy notice per drop; thresholds configurable in settings. |
| Weight/dims | Gemma **estimates from photos** at listing time; a **pre-filled confirm step** at ship time before rates are quoted (wrong-weight labels cost real money). |
| Batch capture | **v1** — the capture flow is a queue from day one (snap N items back-to-back, drafts process in background, review stack). |
| Pulse accent | **Copper** — `PulseAccent.Copper`, registered in the Pulse repo at Phase 0. |
| Notifications | **ntfy** (suite precedent from the Dragonfly digest) for sale events, buyer messages, and price drops. |

---

## 1. Product summary

Crate minimizes selling an item to: (1) take a photo, (2) approve a listing, (3) put
the item in a box and drive it to a shipping location. Everything else is automated.

The pipeline:

1. **Capture** — photograph item(s), multiple angles supported. Batch mode from day
   one: snap several items in one session; each becomes a queued draft processed in
   the background while you keep shooting.
2. **Clean up** — automatic background removal/replacement (white/neutral), crop,
   straighten, and lighting/color correction on each photo before use.
3. **Identify** — Gemma vision (via LM Studio) identifies the item, brand/model if
   applicable, and estimates condition (New / Like New / Good / Fair / Poor). Also
   estimates shipping weight/dimensions from the photos + category (confirmed later,
   at ship time).
4. **Duplicate check** — compare against the registry; if the item matches a prior
   listing pattern (e.g. same lure model sold before), reuse the prior listing
   template and skip re-identification.
5. **Price research** — pull **active** comps via the Browse API, filtered by
   condition, and compute two prices: **quick-sale** (aggressive — undercut the
   cheapest credible active comp) and **patient** (median of actives, for max
   return). Honest labeling in the UI: these are active-market prices, not solds.
6. **Listing draft** — generate title, description, category, item specifics; attach
   both price options; use the cleaned-up photos.
7. **User review** — approve/edit the listing and pick a price strategy (or type a
   specific price). Nothing posts without this step.
8. **Post** — create/publish the listing via the eBay Sell APIs (Inventory + Offer).
9. **Registry log** — item, photos, condition, prices, category, dates, listing id,
   status (`draft → active → sold → shipped`, plus `returned`/`delisted`).
10. **Sale detection** — poll eBay (Fulfillment API) for order status; on sale, pull
    the buyer address and paid amount, send an ntfy notification.
11. **Shipping recommendation** — show the AI weight/dims guess pre-filled for
    confirmation, then compare carrier rates (USPS/UPS/FedEx via Shippo) and
    recommend cheapest/fastest per user preference.
12. **Label purchase** — buy the label via Shippo, push the tracking number to the
    eBay order (Fulfillment API), deliver the label PDF to the phone.
13. **Buyer messages** — incoming buyer questions / return requests are flagged as
    ntfy notifications + an in-app inbox, not passively tracked.
14. **Auto-relist/price drop** — unsold after 14 days ⇒ automatic −10% drop (ntfy
    notice), repeating every 14 days down to the quick-sale floor; at the floor and
    still unsold, Crate asks (notification) whether to hold, relist fresh, or delist.

Explicitly **not** v1: auction-format listings (fixed-price only), international
shipping, multi-marketplace (Poshmark/Mercari — eBay only), bookkeeping/tax reports.
A `/cross-app/summary` endpoint feeding the Dragonfly weekly digest ("Money" card:
listed/sold/net this week) is a natural post-v1 phase.

---

## 2. Stack & ecosystem decisions (already made — do not relitigate)

- **Client:** Android, Kotlin, Jetpack Compose, MVVM + repository, Room + Retrofit —
  mirror Cookbook's client architecture. Room is used for the capture queue (photos +
  draft state must survive process death and upload over WorkManager) and a read
  cache of the item registry; the server is the source of truth.
- **Backend:** Python FastAPI, SQLAlchemy 2.0 async + Alembic, Postgres, same layout
  as Cookbook (`app/routers|services|models|schemas`), same lint/test tooling
  (pytest + ruff, same configs).
- **Own backend, own DB, own users table** (SSO find-or-create). One-app-one-backend
  stays the rule; any cross-app need uses the established patterns (RS256 suite
  tokens, `CROSS_APP_SECRET` JWTs) — no shared monolith.
- **Deployment:** Docker Compose (`db`, `server`) on the Dragonfly host. Host ports
  **API 8007, Postgres 5438**. 8000–8006 / 5432–5437 are taken by
  Spotter/Plate/posterizarr/Cookbook/dragonfly-id/**Magpie**/**Remnant** — the original
  8005/5436 pick collided with Magpie and was corrected at first deploy. Verify against
  `docker ps` on the host, not `netstat` (Docker Desktop's proxy reports these binds free).
  Migrations on boot,
  `GET /health` + `GET /version` (unauthenticated), self-hosted GitHub Actions
  runner (`crate` label) redeploy — clone Cookbook's `deploy/` setup. **No
  cloudflared / no `tunnel` profile**: Crate is tailnet-only, reached at its
  Tailscale Serve URL (Magpie precedent — record the exact ts.net URL here once
  served). It handles buyer addresses and money; keep it off the public internet.
- **Suite conventions Crate must uphold:**
  - `/version` reports `{name, version, commit, built_at}`; CI publishes a signed
    release APK + `version.json` on any `android/**` push to `main` (`release.yml`,
    epoch-minutes versionCode, suite signing key, `apksigner` guard pinned to
    `5a596c9e…`; the release job checks out the sibling **Pulse** repo).
  - Config broker: `util/SuiteConfigReader` reads
    `content://com.dragonfly.suiteconfig/config/crate` in `App.onCreate`, falling
    back to local prefs (copy Cookbook's reader).
  - **Compose env rule:** required non-secret config lives in `docker-compose.yml`'s
    `environment:` block; secrets in `server/.env`. Compose does not re-read changed
    `env_file` on recreate — this has caused production regressions twice.
  - **Cross-repo registrations at Phase 0** (small PRs in sibling repos):
    Dragonfly `AppRegistry` + manifest `<queries>` gain
    `crate | com.crate | CDRaab01/Crate`; dragonfly-id gains the `crate` static
    OIDC client (redirect `com.crate:/oauth2redirect`) and a `crate` smoke client +
    `crate-smoke@dragonflymedia.org` in `SMOKE_SUBJECT_EMAILS`; Pulse registers the
    Copper accent (§3).
- **AI:** LM Studio only, server-side, following the house guardrail model — vision
  output is validated/salvaged server-side, drafts are never auto-committed, the
  user confirms before anything posts. See §9 for the one documented exception
  (the deterministic price-drop scheduler).

---

## 3. PULSE (shared library)

- Consume `design.pulse:pulse-ui` via Gradle composite build
  (`includeBuild("../../Pulse")`; sibling checkout, CI checks it out too) — never
  copy tokens/components in-tree.
- **Crate leads Copper** — a warm metallic brown-orange (cardboard box / packing
  tape). `PulseAccent.Copper` does not exist yet: **Phase 0 adds it to the Pulse
  repo** (additive token change with defaults; register the accent claim in Pulse's
  CLAUDE.md table; regenerate `pulse-index.json` only if a public API changes —
  an accent addition is tokens-only). Verify it reads distinctly against Cookbook's
  amber in both themes before recording baselines.
- **Crate channel semantics** (app-side `ui/theme/CrateTheme.kt`, hues from the
  shared palette): **copper** = hero/primary actions and the listing lifecycle;
  **recovery green** = sold/shipped/done; **electric blue** = pricing/comps data;
  **streak amber** = attention (stale listing, buyer message, action needed);
  violet stays a supporting/provenance accent.

---

## 4. Data model (backend)

- `users` — id, email, name, created_at. SSO find-or-create by email; **no password
  hash column needed** (SSO-only), mirror Magpie.
- `items` — id, user_id, title, description, category_id (eBay category), condition
  (`new|like_new|good|fair|poor`), status
  (`draft|active|sold|shipped|returned|delisted`), quick_sale_price, patient_price,
  chosen_price (nullable until approved), currency, ebay_listing_id (nullable),
  ebay_offer_id (nullable), weight_oz_est, dims_in_est (JSON `{l,w,h}`),
  weight_confirmed (bool), template_id (nullable FK), date_listed (nullable),
  created_at. Status transitions live in one service module; `days_since_listed`
  is computed, never stored.
- `item_photos` — id, item_id, order, original_path, cleaned_path (nullable until
  processed), ebay_url (nullable — eBay Picture Services URL after upload),
  created_at. Binaries live on a server volume (`/data/photos`, bind-mounted,
  survives redeploys); the DB stores paths only.
- `sales` — id, item_id, ebay_order_id, sale_price, fees (nullable), sale_date,
  buyer_username, buyer_address (JSON), ship_status
  (`pending|label_bought|shipped|delivered`), tracking_number, carrier, service,
  label_cost, label_url (nullable), created_at.
- `buyer_messages` — id, item_id (nullable — messages can be pre-sale),
  ebay_message_id, message_type (`question|return_request|other`), content,
  flagged_at, resolved (bool).
- `duplicate_templates` — id, user_id, item_signature (**normalized text**:
  casefolded brand+model+category tokens — not embeddings; LM Studio vision gives
  no image-embedding path and text signatures are testable), title_template,
  description_template, category_id, condition_notes, last_used_price, use_count,
  last_used_at.
- `price_events` — id, item_id, old_price, new_price, reason
  (`auto_drop|manual|floor_reached`), created_at. History for the drop scheduler
  and the UI.
- `ebay_credentials` — single-row-per-user OAuth token store: access_token,
  refresh_token (**encrypted at rest** — Fernet with a key from `server/.env`),
  expires_at, refresh_expires_at, environment (`sandbox|production`), scopes.
  Refresh tokens last ~18 months; surface expiry in the app well before it hits.
- `settings` — per-user: price-drop interval/step/floor behavior, shipping
  preference (`cheapest|fastest`), ntfy topic override. Seeded defaults.

Pricing/drop math lives in **one pure backend module** (`app/pricing/`), exhaustively
unit-tested (Cookbook's `lists/merge.py` precedent): comp filtering (condition match,
outlier trimming), quick/patient computation, drop stepping + floor clamping.
Clients display, never compute.

---

## 5. External services

- **eBay APIs** (all server-side; key/secret in `server/.env`; **always mocked in
  CI**):
  - **Browse** (application token via client-credentials): active-comp search.
  - **Sell — Inventory + Offer** (user token): create inventory item, upload photos
    (eBay Picture Services), publish fixed-price offer.
  - **Sell — Fulfillment** (user token): order polling (Crate polls out on a
    scheduler — no inbound webhooks, consistent with tailnet-only), buyer address,
    pushing tracking.
  - **OAuth:** authorization-code flow for the user token, completed **once** from a
    browser on the tailnet against Crate's `/ebay/connect` → eBay consent →
    `/ebay/callback` (the redirect URI/RuName points at the ts.net URL). Tokens
    persist in `ebay_credentials`; a scheduler refreshes access tokens.
  - **Human-gated:** creating the developer account, sandbox keyset, production
    keyset (requires eBay's **marketplace-account-deletion notification
    subscription or exemption** — as a personal single-seller app storing only
    the owner's data, apply for the exemption), and the one-time OAuth consent.
    Build order never blocks on these: every eBay phase lands mocked-green first,
    then gets a live sandbox/production smoke when credentials arrive.
- **Shippo** (`SHIPPO_API_KEY` in `.env`; test mode in dev; mocked in CI): address
  validation, rate shopping (USPS/UPS/FedEx), label purchase (PDF), refunds for
  misprints. 503 with a clear message when the key is unset (Spoonacular precedent).
- **LM Studio vision** (`LM_STUDIO_BASE_URL=http://host.docker.internal:1234/v1` and
  the model pinned in compose `environment:` — currently `google/gemma-4-e4b`
  suite-wide; if scans 502, check `GET :1234/v1/models` for what's actually
  loaded): item identification, condition estimate, weight/dims estimate. Port
  Cookbook's `services/ai/` transport (`_chat_vision`), strict-JSON prompts, and
  the forgiving parser (fence-stripping, widest-object-span salvage); transport
  failures map to 503/504/502, content failures degrade to a low-confidence draft.
- **rembg + Pillow** (server-side, local CPU, no cloud): background removal → white
  replacement, auto-crop to subject bounds, straighten, levels. The U2-Net weights
  download on first use — bake them into the Docker image so the container works
  offline and cold-starts fast.
- **ntfy** (`NTFY_BASE_URL` + `NTFY_TOPIC` in compose `environment:`; silently off
  when unset — Dragonfly digest precedent): sale events, buyer messages, price
  drops, floor-reached prompts, token-expiry warnings.

---

## 6. Feature flows

**Batch capture → draft:** camera screen with a running queue chip (N pending). Each
item = 1–8 photos, downscaled client-side to ≤1600px JPEG (`util/ImageBytes.kt`
precedent — camera captures blow the upload cap otherwise), persisted to the local
queue (Room + files), uploaded by WorkManager when connected. Server processes each
draft async: cleanup → identify → dup-check → price → draft ready. The app shows a
review stack; each card = photos, identified item, condition, both prices, editable
everything. Approve ⇒ post; dismiss ⇒ delete or park as draft.

**Duplicate fast-path:** if the normalized signature matches a `duplicate_template`,
the draft pre-fills from the template (title/description/category + last price
rescored against fresh comps) and is badged "from template — previously sold N
times"; identification still runs but only to confirm the match.

**Sale → ship:** the order poller (every 15 min) detects a sale ⇒ status `sold`,
ntfy ping. The Ship screen shows buyer address, the pre-filled weight/dims guess
(editable — this is the confirm step), then Shippo rates sorted per preference.
One tap buys the label ⇒ tracking pushed to the eBay order, label PDF opens/shares
for printing, status `shipped`.

**Stale listings:** a daily scheduler finds active items past the drop interval,
applies the step (never below the quick-sale floor), records a `price_event`,
updates the eBay offer, sends ntfy. At the floor + one more interval unsold, ntfy
asks hold / relist / delist; the app's item screen offers the same three actions.

**Buyer messages:** the poller also pulls new buyer messages/return requests ⇒
`buyer_messages` rows + ntfy. In-app inbox lists unresolved items; replies happen
in the eBay app (deep link) — Crate flags, it doesn't chat (v1).

---

## 7. Build phases (each ends with green tests + green CI)

**Phase 0 — Scaffold + suite registrations**
- Pulse: add `PulseAccent.Copper` (+ accent-claim row in Pulse CLAUDE.md); verify
  all consumers still build. Crate repo: Android skeleton consuming `pulse-ui`
  (CrateTheme, copper-led), FastAPI skeleton with `/health` + `/version`, Docker
  Compose (8007/5438), CI (ruff + pytest + assembleDebug both sides), `release.yml`
  cloned from Cookbook (suite signing, Pulse checkout, apksigner guard).
  Sibling PRs: Dragonfly registry + `<queries>`; dragonfly-id `crate` OIDC client
  + smoke client/allowlist.
- Exit: empty app builds with the copper theme; CI green; trivial tests pass.

**Phase 1 — SSO auth + data model**
- `POST /auth/suite` (clone Magpie's SSO-only shape: JWKS validation, find-or-create
  by email, feature-flagged on `SUITE_JWKS_URL`/`SUITE_ISSUER` pinned in compose
  `environment:`), AppAuth client (`SuiteAuthManager`, client id `crate`, redirect
  `com.crate:/oauth2redirect`, **keep the AppCompat theme override on
  `RedirectUriReceiverActivity`**), `synthetic_smoke.py`. Alembic `0001` for all §4
  tables.
- Exit: "Sign in with Dragonfly" works against the live identity server; schema
  migrates cleanly; repo-layer tests pass.

**Phase 2 — Capture → cleanup → identify (no eBay)**
- Batch capture queue (camera + gallery, downscale, Room queue, WorkManager
  upload), `POST /items/scan` pipeline: rembg/Pillow cleanup, Gemma identify +
  condition + weight/dims estimate, draft persisted. Review stack UI with full
  editing. Vision + cleanup mocked in CI; live LM Studio smoke locally.
- Exit: photo → reviewed draft end-to-end on device against real LM Studio.

**Phase 3 — Registry + duplicate templates**
- Item list/detail screens (status lifecycle, photos, price history), signature
  normalization + template matching (pure module, table-driven tests), template
  create-on-sale + reuse-on-capture flows.
- Exit: re-capturing a templated item pre-fills from the template; lifecycle
  transitions covered by router + VM tests.

**Phase 4 — Pricing research**
- `app/pricing/`: Browse API client (mocked in CI), condition-filtered comp pull,
  outlier trim, quick/patient computation; comps shown in the review UI (top
  actives with links). Requires at minimum a sandbox/app token — if no eBay
  account exists yet, land fully mocked and add the live smoke when keys arrive.
- Exit: drafts carry both computed prices with visible comp evidence; pricing
  module exhaustively unit-tested.

**Phase 5 — eBay OAuth + posting**
- `/ebay/connect` + `/ebay/callback` (one-time consent over the tailnet), token
  store + refresh scheduler, Inventory/Offer posting, photo upload to eBay Picture
  Services, honest error surfaces (401 not-connected vs 502 eBay-down). Sandbox
  first; production cutover is a config change + human-gated keyset.
- Exit: approve in the app ⇒ live listing in the eBay sandbox; all posting paths
  mocked-tested in CI.

**Phase 6 — Sale detection + buyer messages + notifications**
- Order/message poller (15-min scheduler), `sales` + `buyer_messages` writes,
  ntfy integration, in-app inbox + sold-state UI.
- Exit: a sandbox sale flips the item to sold, pings the phone, and shows the
  buyer address in-app.

**Phase 7 — Shipping**
- Weight/dims confirm screen, Shippo rate shop + label purchase (test mode),
  tracking push to the eBay order, label PDF share/print, `ship_status` lifecycle.
- Exit: sandbox sale → confirmed weight → test label bought → tracking on the
  order → status `shipped`, end-to-end.

**Phase 8 — Auto price-drop + polish + release**
- Drop/relist scheduler (+ settings screen for thresholds), floor-reached flow,
  empty states, Roborazzi baselines (light + dark), deploy live (runner +
  redeploy + Tailscale Serve), tagged APK via `release.yml`, README,
  ARCHITECTURE.md complete.
- Exit: v1 feature-complete, deployed tailnet-only, CI/CD green end-to-end.

---

## 8. Testing & CI

- **Backend:** table-driven unit tests for pricing/drop math, signature matching,
  and the vision parsers; router tests against a test DB; **eBay, Shippo, LM
  Studio, and ntfy always mocked in CI**. pytest + ruff, same configs as Cookbook.
- **Local test recipe** (suite-standard, do not rediscover): throwaway DB in the
  crate-db container, `DATABASE_URL` host **127.0.0.1 never localhost**,
  `DB_NULLPOOL=true` (pooled asyncpg connections bind a dead event loop otherwise).
- **Android:** VM + repository/queue/sync unit tests; Roborazzi screenshot
  baselines (dark + light), `workflow_dispatch` job like the siblings.
- **CI:** every PR — lint, format-check, unit tests both sides, assembleDebug;
  block merge on red. **CD:** self-hosted `crate` runner redeploys green `main`;
  manual `workflow_dispatch` with `ref` as rollback.
- No secrets in repo: eBay keyset, Shippo key, Fernet key, DB creds via env;
  non-secret required config pinned in compose `environment:` (§2 rule).

---

## 9. Conventions & guardrails

- **Update `ARCHITECTURE.md` in the same PR** when a change alters architecture —
  a module's responsibility, a layer boundary, an external contract, or the data
  model (suite-wide rule; silently-drifting docs burned Spotter once already).
- Match the siblings' code style, package naming (`com.crate`), commit style, PR
  scoping. One phase per PR-sized chunk; restate assumptions before coding.
- **AI guardrails (house model):** prompts live server-side in one auditable module
  (`app/services/ai/`); vision output is schema-validated with salvage, degrades to
  a low-confidence draft rather than erroring; **nothing AI-generated posts, prices,
  or purchases without explicit user approval** in the review/confirm steps.
- **Documented exception:** the auto price-drop scheduler writes to eBay without
  per-event approval. It is allowed because it is **deterministic policy the user
  configured** (interval/step/floor in settings), not AI output — it never goes
  below the user-approved quick-sale floor, every drop is ntfy-notified and logged
  in `price_events`. Keep it pure, bounded, and boring.
- **Money-adjacent caution:** label purchase and offer publication always sit
  behind an explicit in-app tap. The only unattended eBay writes are price drops
  (above) and tracking upload (side effect of a user-initiated label purchase).
- Pricing, drop, and signature math centralized and pure; clients display, never
  compute.
- Buyer addresses and OAuth tokens are the most sensitive data in the suite so
  far: tailnet-only exposure, tokens encrypted at rest, and no third-party calls
  beyond eBay/Shippo with the minimum payload each needs.

---

## Build log (2026-07-25) — Phases 0-8 built in one pass

All nine phases landed on `claude/new-session-5pdxtl` (one commit per phase-sized
chunk), verified locally per commit: server **147 pytest green + ruff check/format
clean** against a throwaway Postgres (alembic chain 0001→0002 applies AND downgrades on
a fresh DB); Android **16 unit tests + `:app:assembleDebug` green** against the real
Pulse sibling checkout (SDK bootstrapped in the build container; CI re-verifies with
its own Pulse checkout). Every external service (eBay, Shippo, LM Studio, rembg, ntfy)
is mocked in CI per §8.

- **Suite registrations shipped in sibling repos** (same branch name in each):
  Pulse `PulseAccent.Copper` (base `0xFFD98A5B`, deep `0xFF9A4D1B` — 6.1:1 on white;
  heated-metal hero sweep OrangeDeep→CopperDeep with the white-text guarantee;
  `pulse-index.json` regenerated); Dragonfly `AppRegistry` + `<queries>`; dragonfly-id
  `crate` OIDC client + registration test + `crate-smoke@dragonflymedia.org` in the
  `SMOKE_SUBJECT_EMAILS` compose pin + `SMOKE_CLIENTS` documented in `.env.example`.
  Dragonfly's status-dashboard `ServiceRegistry` entry was deliberately deferred until
  the real ts.net URL exists (the Hawksnest URL-guess lesson).
- **Deviations from the spec above, flagged per §0** (details in ARCHITECTURE.md):
  `items.brand/model` columns added (migration `0002` — the template signature needs
  them at sale time, long after the vision draft is gone) plus
  `processed_at`/`scan_error` scan-pipeline state; the template signature uses
  **brand+model tokens only** (category_hint is transient, so a sale-time signature
  could never reproduce a capture-time one); PATCH clearing uses `exclude_none`
  (kotlinx clients send explicit nulls). Buyer messages are **subject-only** in v1
  (Trading GetMyMessages header detail) — Crate flags, replies happen in the eBay app.
- **Planned tailnet exposure:** Tailscale Serve port **8446** (443/8443/8445 taken);
  the CI/app default server URL is `https://dragonfly.tail2ce561.ts.net:8446/` until
  the real URL is confirmed at first deploy (override via the `CRATE_SERVER_URL`
  Actions variable + the config broker at runtime).
- **Human-gated items (build never blocked on them, everything lands mocked-green):**
  1. eBay developer account → sandbox keyset (`EBAY_CLIENT_ID/SECRET`) → pricing +
     `/comps` go live; RuName pointing at the ts.net callback → one-time OAuth consent
     from a tailnet browser → posting/polling go live; production keyset (apply for
     the **marketplace-account-deletion exemption**) → `EBAY_ENVIRONMENT=production`.
  2. One-time seller setup: business policies (`EBAY_*_POLICY_ID`) +
     `EBAY_LOCATION_POSTAL_CODE`; `FERNET_KEY`; Shippo key + `SHIP_FROM_*`.
  3. Deploy: ~~`crate` runner + `CRATE_DIR` variable~~ **(DONE — runner registered with the
     `crate` label, `vars.CRATE_DIR` set 2026-07-26, first green Deploy 2026-08-14)**,
     ~~Tailscale Serve~~ **(DONE — `:8446`)**, ntfy topic, ~~`crate-smoke` secret in
     dragonfly-id's `SMOKE_CLIENTS` (+ same value in Crate's `.env` for the smoke)~~
     **(DONE — the smoke mints tokens against `id` and passes)**, Dragonfly
     `ServiceRegistry` row once the URL is real.
  4. On-device pass (camera flow, AppAuth redirect, label PDF share) — CI builds are
     the gate until the phone is in hand. Roborazzi baselines **recorded 2026-07-25**
     (`com.crate.screenshot.ScreenshotTest`, 12 PNGs under `android/app/screenshots/`:
     Home/Login/Review/ItemDetail/Ship/Inbox × light+dark; the `workflow_dispatch`
     screenshots job re-runs them, suite pattern). Recording them caught and fixed two
     real UI defects: the review card's price-strategy row overflowed (now `FlowRow`)
     and the Sale card printed the buyer address as raw JSON (now a readable line).
- **Deferred (post-v1, per §1):** `/cross-app/summary` for the Dragonfly digest
  ("Money" card), buyer-message full bodies + in-app replies, auction format,
  international shipping, multi-marketplace, bookkeeping.

## Visual redesign round (2026-07-25) — brand kit + navigation shell

User-driven polish pass ("look professionally designed, not a science project");
decisions locked with the user: bottom tabs, a Crate-only display font for branding
moments, a geometric crate glyph. Android-only; no server/VM-contract changes beyond an
additive `HomeViewModel` + `SettingsViewModel.user` (both on existing endpoints).

- **Brand kit:** `ui/components/CrateBrand.kt` (`CrateGlyph` isometric open-box vector,
  `CrateWordmark` in **Saira Stencil One** (OFL, bundled TTF; FontFamily internal to the
  brand file — stencil never leaks into UI text), `BrandLogo` tile). Launcher icon
  rebuilt: hero-gradient background (suite pattern), glyph foreground with safe-zone
  group, **plus a `<monochrome>` themed-icon layer — first in the suite**.
- **Shell:** 5 bottom tabs (Home/Sell/Review/Registry/Inbox) on existing routes;
  detail routes get back-arrow TopAppBars; `consumeWindowInsets` per the suite
  double-insets landmine. Settings moved behind the Home hero's gear.
- **Home became a dashboard** (HeroPanel + StatTiles + attention card + recent strip);
  every screen now uses the wider Pulse set (EmptyState/ErrorState, segmented control,
  selectable price-strategy cards, SettingsSection/ProfileHeader, ChannelDot,
  Sparkline). Dev-facing copy ("arrives in Phase N", keyset talk) replaced with product
  copy; Settings gained the missing `verticalScroll` (overflow bug).
- **Verified:** `:app:testDebugUnitTest` green (33 tests incl. new `HomeViewModelTest`);
  Roborazzi baselines re-recorded — 16 PNGs (adds settings + shell scenes).
- **Spacing pass (same day, from on-device review):** Pulse's `PanelCard` lays out content
  with a zero-gap Column by design, so every stacked card interior now supplies its own
  rhythm — 8dp between related lines, ~12dp before section transitions, 4dp title/badge
  grouping (DraftCard, MessageCard, Detail panels, WeightConfirmCard/LabelBought, Settings
  cards). Baselines re-recorded again.
- **Polish round (same day):** (1) price-strategy cards are full-width rows (name left,
  mono price right) — the half-width pair wrapped "Patient" on-device; (2) freshness:
  `util/OnResumeEffect` (back-stack-entry lifecycle, skips the synthetic first ON_RESUME)
  refreshes Home/Review/Registry/Inbox on every tab revisit, plus `PulseRefreshBox`
  pull-to-refresh on the three list screens (additive `refreshing` StateFlows; Registry
  refresh keeps content on screen — only a filter change shows the spinner); (3) queueing
  a capture confirms via snackbar; (4) tab navigation anchors `popUpTo(Home)` instead of
  the graph start (Gate pops itself, so the old anchor was a no-op and tabs piled up on
  the back stack — back now always lands on Home, then exits).

## Archive-first round (2026-08-12 → 08-14) — apparel capture, real backups, real-image tests

Landed as `04712c8` (#12). Premise: with no eBay keyset yet, Crate's near-term job is a
**wardrobe archive**, and the data that only exists on the physical garment — the tag and the
tape measure — is gone the moment the item is boxed. So capture it while the garment is in hand.
Details in ARCHITECTURE.md (§"Apparel + archive completeness", §"Backups",
§"Photo pipeline verification"); this entry is the summary that was missing from CLAUDE.md.

- **Apparel item specifics:** migration `0003` adds `item_kind`, `size`, `size_type`,
  `department`, `color`, `material`, `style`, `fit`, `sleeve_length`, `measurements_in`,
  `storage_location`. `app/apparel/` holds the pure logic — `attributes.py` (controlled
  vocabularies, forgiving-shape/strict-membership `normalize_enum`, bounds-checked
  `normalize_measurements`) and `completeness.py` (`missing_for_listing` vs the urgent
  `missing_hand_only`). Both surface as `@computed_field`s on `ItemOut` (§9: clients display,
  never compute). **Deliberate write-path asymmetry:** vision output degrades (unknown enum →
  null), a hand `PATCH` rejects (422).
- **Backups:** `deploy/backup.ps1` writes a timestamped `db.dump` + `photos.tar.gz` +
  `MANIFEST.json` outside Docker, verifies before claiming success, and prunes to `-Keep` only
  after the new set verifies. Restore runbook in `deploy/README.md`.
- **Real-image pipeline tests:** `tests/fixtures/images.py` (Pillow-built, no binaries in git)
  + `tests/test_photo_pipeline.py`, plus `scripts/photo_smoke.py` for driving real photographs
  at a running server. Every earlier scan test uploaded fake PNG bytes with `clean_photo`
  monkeypatched, so no pixel had ever been decoded.
- **The defect those tests caught:** `clean_photo` ran `autocontrast` *after* white-background
  replacement, so the garment — the darkest content in that composite — was clipped to
  `(0,0,0)` in every colourway, with a colour cast pushed into the background. Levels now run
  on the original capture with `preserve_tone=True`, before compositing.
- **Verified at the time:** 271 pytest green + ruff clean; CI green. Everything below was
  explicitly *not* verifiable in the build container (no U2-Net, no LM Studio, no Docker
  daemon) and carried forward — which is what the next round is about.

## Verification round (2026-08-14) — proving the untested half on the real host

No new features. The archive-first round shipped three things it could not exercise, so this
round ran them against the live Dragonfly host (rembg with real U2-Net weights, real LM Studio
serving `google/gemma-4-e4b`, a real Docker daemon) using **19 permissively-licensed real
photographs** (Wikimedia/Unsplash CC0–CC BY-SA) downscaled to the client's ≤1600px contract.
Photos stayed in a scratchpad — no binaries in git, per the fixtures design.

- **rembg segmentation: works on real photographs.** Across 17 scanned items, 15 came back with
  4/4 pure-white corners and a tight crop-to-subject; the two partials were a clothing *rack*
  (~30 garments — no single subject to segment, correctly) and a flat label close-up.
- **The levels fix holds on real pixels.** The dark-navy denim control went from a grey backdrop
  at centre-mean `(41,45,54)` to `(72,77,87)` on pure white with **0.03% pure-black**; the
  black-dress case kept its tone and fabric folds. Highest pure-black in any cleaned output was
  0.66%, and that was legitimate black text on a label. The blackening defect is genuinely gone.
- **Real Gemma returns usable JSON** — ~15 s per item, well inside the 60 s `lm_studio_timeout`,
  parsed by `parse_identify` without salvage drama. Worth recording: gemma-4 **is** a reasoning
  model here and returns `reasoning_content` alongside `content`, so `_chat_vision` reading only
  `content` is correct — and `vision.py` deliberately setting **no `max_tokens`** is what keeps
  it safe. An answer-sized cap would let hidden reasoning tokens eat the budget and silently
  return `""`, which the parser would read as "unidentifiable" (the suite-wide gemma-4 trap).
- **The size invariant holds, and an attempt to "improve" it was rejected on evidence.**
  Ground truth was read by eye off 8 tag photographs (X-LARGE; 中/小/大; a circled `S` in an
  `XS S M L XL XXL` run; `EUR 30 / US 30`; two brand/care-only negative controls). Measured
  over 3 runs of an A/B harness driving the **real** `build_identify_messages`/`parse_identify`:
  the shipping prompt scored **24/24 on safety — it never once invented a size** — while reading
  only ~1/6 of legible ones. A candidate prompt that told the model "reading is not inferring"
  produced **no recall gain and a reproducible wrong answer** (`M` for the circled-`S` label, 3
  runs out of 3). **No prompt change shipped.** Under-reading is the designed trade: a null
  sends a human to the tag, a wrong size ships the wrong garment. Direct probing confirms the
  model *can* read these tags when asked plainly, so the recall gap is real but must not be
  closed by weakening the never-infer rule.
- **`backup.ps1` had never actually run — it could not.** Line 248 wrote the dump with
  `Set-Content -AsByteStream`, which is **PowerShell 7+ only**; the host has no `pwsh` and its
  `powershell.exe` is **5.1**, so the script threw on its first step and left an *empty*
  timestamped directory — a backup set that looks present until you open it. Fixed by
  redirecting `pg_dump` through `cmd` straight to disk (binary never enters the 5.1 pipeline,
  which would decode it to text and corrupt it; `-Encoding Byte` is no good either, being gone
  in 7). Now verified end-to-end: `PGDMP` magic bytes, `pg_restore --list` reads 55 TOC entries,
  17.4 MB photo archive, `-Verify` green. **Restore is still unrehearsed** — deliberately, since
  proving it means `pg_restore --clean` against the live database.
- **Weekly CI had been red for three straight weeks** (2026-07-27 / 08-03 / 08-10) on
  `pip-audit`, and the job's own comment says a red weekly run is the signal to look. The sole
  cause was `ecdsa` PYSEC-2026-1325 (Minerva timing attack), which has **no fix version** —
  upstream considers side channels out of scope — and is present only because `python-jose`
  declares it. Crate never reaches it: local tokens are HS256, suite tokens are decoded with
  `algorithms=["RS256"]` pinned, so no EC signing/keygen/ECDH ever runs. Ignored explicitly with
  that reasoning so the weekly signal means something again; the real remediation (drop
  python-jose for PyJWT) is recorded at the ignore. `pytest` 8.4.2 is also flagged
  (PYSEC-2026-1845, fixed in 9.0.3) but 9.x conflicts with `pytest-asyncio` 0.26.0, and CI's
  audit installs runtime deps only — pinned with a comment rather than bumped blind.
- **Two small defects fixed, both found by using the tools rather than reading them:**
  `photo_smoke.py` printed a hardcoded "LM Studio is unreachable" remediation for *any* failure,
  so an ordinary `low_confidence` draft sent you debugging container networking that was fine —
  it now names the failing photo, prints the real `scan_error`, and matches the hint to it. And
  `scan_pipeline.py` recorded `identify_unavailable` without logging it, so a real LM Studio
  outage left no trace in `docker logs`; it now logs a warning.
- **Roborazzi: verified before re-recording, and only 2 of 16 baselines were actually stale.**
  `item_detail` was *not* stale despite being assumed so. `review_light`/`review_dark` changed
  by ~470k pixels — the archive-first round's "Garment details" button, which appears on every
  draft by design (a general good misclassified from a garment needs a route into the tag
  fields). Recording rewrites all 16 files, but the other 14 differed by only 78–878 px of
  anti-aliasing jitter, so they were restored: the commit shows the two that changed meaning.
- **Verified:** server **271 pytest green**, `ruff check` **and** `ruff format --check` clean
  (CI runs both); Android **28 unit tests** + all **16 Roborazzi baselines** verify green.
  Deploy was already live before this round — the "runner + `CRATE_DIR` still human-gated" note
  above was stale, first green Deploy having run 2026-08-14 with its post-deploy smoke passing.
- **Still unverified, honestly:** backup *restore* (above); the on-device pass; and everything
  eBay/Shippo, which is still keyset-gated. The photographs used here are real but they are not
  *this wardrobe* — a run of `photo_smoke.py --dir <folder>` against the owner's own garments,
  in the owner's lighting, on the owner's phone camera, is still worth doing and is what
  `scripts/photo_smoke.py` was written for.

## Silent-failure round (2026-08-14) — backups, alerting, and a smoke that means something

The verification round proved the pipeline works. This one closes the three ways Crate could
fail **without telling anyone** — each found by checking the host rather than reading the docs.
Spans repo *and* host: the scheduling/encryption half lives in `C:\Scripts` (see OPERATIONS.md
§9), because the host convention is that repo scripts produce a verified set and `C:\Scripts`
promotes it.

- **The wardrobe photos had no backup at all.** The nightly `Dragonfly DB Backup` covers Crate's
  database (added 2026-08-05, landing daily) but is pg_dump-only and has never touched a Docker
  volume. `/data/photos` was covered solely by `deploy/backup.ps1`, which had **no scheduled
  task** and, until the previous round, could not run. For a wardrobe archive the photographs
  *are* the artifact; the rows are paths pointing at them. Now: `C:\Scripts\Backup-CrateArchive.ps1`
  (task "Crate Archive Backup", daily 04:30, offset from the 03:30 DB job) → gpg AES-256 → NAS,
  30-day prune. **Verified by decrypting what landed**, not by watching it upload: `PGDMP`
  header, `pg_restore --list` reads 55 TOC entries, the photo tar lists 52 entries.
- **Nothing reported a red run.** No `if: failure()`, no ntfy, no notification of any kind in any
  workflow in *any* suite repo — which is why `pip-audit` sat red for three weeks. `notify.yml`
  is the first, and the other six repos can copy it. It must run on the self-hosted runner (the
  suite ntfy is tailnet-only on `:8095`), which is exactly why it cannot be an `if: failure()`
  step inside `ci.yml` — `ci.yml` has a `pull_request` trigger and invariant 7 forbids a
  self-hosted job being reachable from one. All `workflow_run` metadata is passed via `env:`,
  never interpolated into the shell: it fires for fork PRs with base-repo privileges, and a
  branch name is attacker-controlled text on the prod host.
- **`NTFY_TOPIC` was unsettable, not merely unset.** Compose interpolated `${NTFY_TOPIC:-}` from
  a root `.env` that this repo does not have, so it resolved to empty every time and *every*
  notification (sale detection, price drops, floor-reached, token expiry) was silently off —
  the same class as the §2 compose-env rule's own cautionary tale. Now literals, pointed at the
  self-hosted ntfy rather than public ntfy.sh: topic `crate-alerts`, per the suite's
  `<domain>-alerts` convention, for an app that deliberately stays off the public internet.
- **The post-deploy smoke proved the wrong thing.** It stopped at `/users/me`, so auth working
  read as Crate working. It now pushes a generated PNG through `/items/scan` and asserts the
  draft processed, the photo came back `cleaned`, and the bytes are servable — then always
  deletes the draft. Strict on `identify_unavailable` (fails the deploy), lenient on
  `low_confidence` (a synthetic rectangle is legitimately unidentifiable). **All four branches
  were exercised live** against an isolated throwaway container: healthy → pass; dead
  `LM_STUDIO_BASE_URL` → fail (503); wrong `LM_STUDIO_VISION_MODEL` → fail (502, which means it
  catches the model pin too, not just the URL); and a stubbed LM Studio forcing `low_confidence`
  → pass. Deploy grows ~45 s. The test image is hand-built from `zlib`+`struct` because the
  smoke runs inside the container, whose image has Pillow but not `server/tests/`.
- **The freshness alarm that had been open since the two-week silent outage** (OPERATIONS.md §8)
  is now in the weekly `Test-SuiteInvariants.ps1`, which already pages `dragonfly-alerts`. It
  asserts the newest **artifact's age** (36 h), never the task's configuration — the whole lesson
  of 2026-07-27 → 08-10, when `Get-ScheduledTask` cheerfully reported `Ready` throughout. All
  four branches tested: stale → FAIL, 0-byte → FAIL, missing → FAIL, fresh → PASS. The 0-byte
  case is precisely what the `-AsByteStream` bug produced.
- **Two bugs found by *using* the tools rather than reading them.** `backup.ps1` failed on an
  empty photo archive: `$MinPhotosBytes` (100) is meant to catch a truncated tar, but an empty
  gzipped tar is ~45 bytes, so a Crate with no items yet would have failed its backup every
  single night until the first scan — a nightly false alarm, the fastest way to train someone
  to ignore a real one. The floor now yields when the row count is *known* zero. And
  `decode_body` in both smoke scripts stringified JSON **arrays** into a 200-char `repr`, making
  list endpoints unreadable; `GET /items` now returns intact under `_list` (which is how the 17
  leftover drafts were enumerated and cleared).
- **Verified:** server **271 pytest green**, `ruff check` **and** `ruff format --check` clean;
  `docker compose config` resolves the ntfy literals as intended. The live DB is back to **zero
  items** — the correct starting state before real archiving.
- **Still not done, deliberately:** backup **restore** into a live database (proving it means
  `pg_restore --clean` against prod — the artifacts are proven restorable, the procedure is not);
  exercising the ops scripts from CI; relocating `CRATE_DIR` off the dev checkout; replacing
  python-jose with PyJWT; and the tag-reading second pass. Each wants its own change.
