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
- **Tailnet-only:** the API is published on `127.0.0.1:8007` and reached via Tailscale
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

### UI shell + brand kit (visual redesign round, 2026-07-25)

- **Navigation shell**: `ui/navigation/TopLevelDestination.kt` (5 tabs — Home, Sell
  → capture, Review, Registry → items, Inbox — reusing existing routes) +
  `CrateBottomBar` (Spotter `PulseBottomBar` clone: hairline divider, panel bar,
  copper selection) inside a `Scaffold` in `CrateNavHost`. The NavHost gets
  `Modifier.padding(padding).consumeWindowInsets(padding)` — without it, detail
  screens' inner TopAppBars double-apply system-bar insets (suite landmine). Detail
  routes (item detail, ship, settings) show a back-arrow `TopAppBar` and no bottom
  bar; gate/login show no chrome. Tab navigation uses
  `popUpTo(findStartDestination){saveState}; launchSingleTop; restoreState`.
- **Brand kit**: `ui/components/CrateBrand.kt` — `CrateGlyph` (isometric open-box
  ImageVector, 48-grid; full-color copper or single-tint monochrome via alpha steps),
  `CrateWordmark` ("CRATE" in Saira Stencil One, OFL, bundled at
  `res/font/saira_stencil_one_regular.ttf`; the FontFamily lives in
  `ui/theme/BrandType.kt` and is deliberately internal — stencil is wordmark-only,
  never UI text), `BrandLogo` (hero-gradient tile + white glyph). The adaptive
  launcher icon reuses the same glyph geometry on the hero gradient with a safe-zone
  group, and adds a `<monochrome>` layer (first in the suite).
- **Home is a dashboard**: `HomeViewModel` (reuses `GET /items` + `GET
  /messages?unresolved_only=true`; errors degrade to zeroed stats) feeding a stateless
  `HomeContent` — HeroPanel with glyph/wordmark/settings gear, three dense StatTiles
  (Active/Sold/Drafts), an attention card when buyer messages wait, and a recent-items
  strip. Counts are display aggregation only; pricing math stays server-side.
- Screens use the Pulse component set (EmptyState/ErrorState, PulseSegmentedControl,
  PulseSelectableCard, SettingsSection/ProfileHeader, ChannelDot, Sparkline, Caption,
  DataText) rather than hand-rolled equivalents; dev-facing copy was replaced with
  product copy in the same round.

## CI/CD

- `ci.yml` — server ruff + pytest (Postgres service, migrations first), Android unit
  tests + assembleDebug (Pulse checked out as sibling), gitleaks, weekly pip-audit.
- `release.yml` — signed release APK + `version.json` on any `android/**` push to
  `main`; epoch-minutes versionCode; apksigner guard pinned to the suite signer
  (`5a596c9e…`).
- `deploy.yml` — self-hosted `crate`-labeled runner redeploys green `main` via
  `deploy/redeploy.ps1`, then runs the synthetic smoke inside the container. An opt-in
  `bootstrap_host` input creates the deployment clone and a minimal `server/.env` when
  absent (never overwrites an existing `.env`). Human-gated setup: runner registration +
  `CRATE_DIR` Actions variable + Tailscale Serve config.
- **Health gate identity check.** The gate polls `127.0.0.1:8007/health` *and* asserts
  `/version` reports `name == "Crate API"`. `/health` returns an identical
  `{"status":"ok"}` in every suite app, so port alone cannot identify the responder — the
  first deploy pointed at 8005, got an instant "ok" from **Magpie**, and declared success
  while Crate was still booting. A neighbour answering is treated as a config error and
  fails immediately rather than retrying to the timeout.

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
   The prompt also carries an **apparel block** (item_kind, department, size, size_type,
   color, material, style, fit, sleeve_length) with one hard rule: report only what is
   legible, never infer a size from how a garment looks. Unrecognized enums are dropped to
   null rather than stored, so an unread tag surfaces as a completeness gap instead of a
   confident wrong answer. There is deliberately no measurements field — a vision model
   cannot use a tape measure, so measurements are human-entry-only.
   `LM_STUDIO_BASE_URL` is pinned in compose `environment:` as
   `http://host.docker.internal:1234/v1`. The config default (`localhost`) is correct only
   for bare-metal local dev — in the container localhost is the container, so relying on the
   default makes every scan degrade to `identify_unavailable` while LM Studio is up and
   healthy on the host.

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

## Apparel + archive completeness (archive-first round, 2026-08-12)

Crate was specified around "photo to shipped package". Without an eBay keyset the pipeline
still runs end to end minus pricing and posting (`price_item` is best-effort by design), so
capture is usable today — which turns the app into a **wardrobe archive** first and a
selling tool later. That reordering has one failure mode worth building against: size,
material and measurements live on the garment's tag and on a tape measure, not in a photo.
Once a shirt is folded into a bin, the only way to recover them is to unbox it.

- `app/apparel/attributes.py` — controlled vocabularies (`DEPARTMENTS`, `SIZE_TYPES`,
  `SLEEVE_LENGTHS`, `FITS`, `MEASUREMENT_KEYS`) plus `normalize_enum` (forgiving on shape:
  "Big & Tall" → `big_tall`; strict on membership) and `normalize_measurements` (inches,
  bounds-checked, unknown keys dropped, empty ⇒ None never `{}`). Size, color, material and
  style stay **free text on purpose** — real tags say "Heather Grey" and "60% cotton".
  These are Crate's enums, not eBay's: mapping to eBay aspect values happens in
  `services/ebay/sell.py` when a keyset exists, rather than guessing the exact strings now.
- `app/apparel/completeness.py` — pure, table-tested. `missing_for_listing` is everything
  eBay will want; `missing_hand_only` is the urgent subset that needs the physical garment
  (brand, size, size_type, department, material, measurements). Both are `[]` for
  `item_kind="general"` — flagging "size" on a fishing lure would train the user to ignore
  the indicator. Surfaced as computed fields on `ItemOut` per CLAUDE.md §9 (clients
  display, never compute).
- **Write paths differ deliberately.** The vision parser *degrades* — an unrecognized enum
  becomes null and resurfaces as a gap. A hand `PATCH` *rejects* (422) — silently NULLing a
  value the user believes they typed is worse than an error. `item_kind` is NOT NULL, so ""
  clears the other enums but never blanks it.
- Client: `ui/components/ApparelFields.kt` (garment summary line, measurement line, the
  `ArchiveGapRow` nag, and the tag/tape edit dialog), wired into the review card and a
  "Garment" panel on item detail. `storage_location` rides along because a registry that
  cannot say which bin a sold shirt is in is not usable at ship time — which here is months
  away.

## Photo pipeline verification (2026-08-14)

Until this round every scan test uploaded `b"\x89PNG...fakebytes"` with `clean_photo`
monkeypatched to a passthrough, so nothing in the suite ever decoded a pixel — the cleanup,
storage and serving code was covered only by its own signature.

- `tests/fixtures/images.py` — real, decodable garment/product/tag samples built with Pillow
  (no binaries in git, deterministic, self-documenting). `python -m tests.fixtures.images
  <dir>` writes them out to look at. They carry seeded noise, one-sided lighting falloff and
  a blown highlight **on purpose**: a flat two-tone fixture is its own histogram minimum, so
  it makes level-related assertions fail for reasons that never occur on a real photo.
- `tests/test_photo_pipeline.py` — real JPEG/PNG/WebP through the real endpoint and the real
  cleanup: decode, format round-trip, downscale, multi-angle order, the served binary, the
  corrupt-upload degrade, and the whole archive-completion loop. rembg stays disabled (CI must
  never fetch U2-Net); the removal branch is exercised by stubbing `_remove_background` with a
  genuine RGBA cutout, so crop-to-subject and the white composite run on actual pixels.
- `scripts/photo_smoke.py` — the part tests cannot do: send **real photographs** at a running
  Crate and read what Gemma made of them. `--dir` for your own photos, `--each-file` for one
  item per shot, `--samples` for the synthetic set (plumbing only). A draft that comes back
  with a `scan_error` fails the run — a smoke that passes while LM Studio is unreachable is
  worse than no smoke — with `--allow-scan-errors` for a deliberate plumbing-only check.
  `CRATE_ACCESS_TOKEN` skips the dragonfly-id round trip for local runs.

**Defect found and fixed by these tests — levels order of operations.** `clean_photo` applied
`ImageOps.autocontrast(cutoff=1)` *after* background replacement, i.e. to a composite of the
garment plus a field of pure white. `cutoff=1` clips the darkest one percent of pixels **by
count**, and in that composite the garment is by definition the darkest content, so the clip
landed on the garment and mapped it toward black: on a flat, evenly lit tee every colourway —
including a light heather grey — came back pure `(0, 0, 0)`. The per-channel stretch also
drove a complementary cast into the ground (a red shirt turned the backdrop teal), which
matters because eBay wants a white background and `color` is an item specific Crate records.
Levels now run on the **original capture**, before any compositing, with `preserve_tone=True`
so one luminance-derived mapping applies to all three channels. Guarded by
`test_white_replacement_never_blackens_the_garment`,
`test_white_replacement_leaves_the_background_pure_white`, `test_cleanup_keeps_the_garment_hue`
and `test_levels_still_lift_an_underexposed_capture`.

## Backups (archive-first round, 2026-08-12)

`docker-compose.yml` puts the DB in the `pgdata` volume and item photos in the `photos`
volume; the comment there claims only that they *survive redeploys*, which is true and was
being read as a backup story. They do not survive `docker compose down -v`, a disk failure,
or a host rebuild. Crate's registry is now the only record of a wardrobe that has been
photographed, tagged, measured and boxed, so:

- `deploy/backup.ps1` — host-side (Windows/Docker Desktop, same shape and conventions as
  `redeploy.ps1`, including its ASCII-in-quoted-strings cp1252 rule). Writes a timestamped
  set: `db.dump` (pg_dump `-Fc`), `photos.tar.gz` (the volume, read via `--volumes-from` so
  the Compose-prefixed volume name is never guessed), and `MANIFEST.json`. `-BackupDir`
  (or `CRATE_BACKUP_DIR`) should point at **other physical media** — a copy beside the
  original is not a backup. `-Keep` prunes, but only after a verified-good new set exists,
  so a failing run can never delete the last good backup.
- **It verifies before claiming success**, because a trusted empty backup is worse than
  none: both artifacts must be non-trivially sized, and the photo archive must hold at
  least one file per `item_photos` row (originals are written to disk before their row is
  committed, so files >= rows holds on any consistent set). A missing `photos.tar.gz` fails
  unless `MANIFEST.json` records a deliberate `-SkipPhotos`.
- **A dead Docker daemon and a corrupt archive both surface as exit 1** from `docker run`,
  so the daemon is probed separately and tar failure is signalled as exit 3 from inside the
  container. Getting that backwards would either condemn good backups or bless corrupt
  ones. Infrastructure trouble is a warning; only a container that ran and failed marks the
  set bad. The helper container is `postgres:16` (already pulled for the db service) so
  verification needs no registry round trip and works offline.
- `-Verify` re-checks the newest set without writing one. Restore steps: deploy/README.md.

## Auto price-drop scheduler (Phase 8, as built — the §9 documented exception)

- `app/pricing/drops.py` — the pure policy: one step down
  (`current × (100 − step)/100`, cent-quantized) clamped to the quick-sale floor; due
  when the interval elapsed since the LAST CHANGE (listing date or latest price event);
  at the floor for a further interval ⇒ hold/relist/delist prompt exactly once
  (`floor_reached` event is the latch). Unpriced items are left alone entirely.
- `services/drop_scheduler.py` — the daily pass (lifespan task, first run 1h after
  boot). Per item, own session. **eBay first**: the offer update runs before anything
  is recorded locally, so a rejected update rolls back and the local price never lies
  about the live listing; the next pass retries. Every drop = a `price_events` row + an
  ntfy ping — the audit trail is what makes this unattended write acceptable.
- `GET/PATCH /settings` — the policy knobs (enabled/interval 1-90d/step 1-50%/shipping
  preference), bounds-checked so a typo can't become a strategy.
- `POST /items/{id}/relist` — republish a withdrawn offer (delisted/returned → active),
  explicit tap like every listing write.
- Client: Settings gains the drop-policy card + shipping preference; item detail gains
  Delist/Relist.

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
  Migration `0003` adds the apparel block — `item_kind` (`clothing|general`, NOT NULL,
  server_default `general` so pre-existing rows are unchanged), `size`, `size_type`,
  `department`, `color`, `material`, `style`, `fit`, `sleeve_length`, `measurements_in`
  (JSON, inches, garment laid flat) and `storage_location`. A second addition over the §4
  sketch, driven by the archive-first workflow: Crate photographs a wardrobe long before
  the eBay keyset exists, and tag/tape data cannot be recovered from a stored photo once
  the garment is boxed (see "Apparel + archive completeness").
- `item_photos` — ordered per item; original_path/cleaned_path on the photos volume
  (DB stores paths only), ebay_url after EPS upload. Cascade with the item.
- `sales` — one per eBay order (ebay_order_id unique): price/fees/date/buyer + address
  JSON, ship_status `pending|label_bought|shipped|delivered`, tracking/carrier/label.
- `buyer_messages` — flagged inbox rows (item nullable — pre-sale questions), unique
  ebay_message_id for poller idempotency.
- `duplicate_templates` — normalized-text signature (not embeddings) + reusable
  title/description/category, use_count/last_used. General goods key on brand+model;
  **clothing keys on brand+model+style+size+department and produces no signature at all
  unless brand AND size are both known** (`matching/signature.py`). Garments seldom have a
  "model", so the general key would degrade to a bare brand and collapse every shirt of a
  brand into one template — which would then overwrite an unrelated garment's title at
  capture time. Size is what makes reuse safe: the same style in M and L are different
  listings with different item specifics.
- `price_events` — audit trail for every drop (auto_drop|manual|floor_reached).
- `ebay_credentials` — one row per user; access/refresh tokens stored encrypted
  (Fernet, Phase 5), sandbox|production environment tag.
- `user_settings` — the drop policy (enabled/interval/step), shipping preference,
  ntfy topic override; seeded at first login.
