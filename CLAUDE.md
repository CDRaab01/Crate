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
| Storage | **Postgres** + SQLAlchemy 2.0 async + Alembic (suite standard; supersedes the early SQLite sketch). Host ports **8005 (API) / 5436 (Postgres)**. |
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
  **API 8005, Postgres 5436** (8000–8004 / 5432–5435 belong to the siblings —
  verify both are still free at Phase 0 and update here if not). Migrations on boot,
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
  Compose (8005/5436), CI (ruff + pytest + assembleDebug both sides), `release.yml`
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
