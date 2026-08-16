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
  absent (never overwrites an existing `.env`). Setup is **done**: the runner is registered
  with the `crate` label, `vars.CRATE_DIR` was set 2026-07-26, Tailscale Serve is on `:8446`,
  and the first green Deploy ran 2026-08-14 with its post-deploy smoke passing.
- **`CRATE_DIR` is a deployment clone, not a dev checkout.** `deploy.yml` runs
  `git -C $CRATE_DIR reset --hard <ref>` on every green `main`, and on the host that path
  (`C:\Code\Crate`) is owned by the runner service account. Never edit or branch there —
  uncommitted work is one deploy away from being erased. Work in a separate clone.
- **The weekly `pip-audit` job ignores `PYSEC-2026-1325`** (`ecdsa`, Minerva timing attack on
  P-256) with the reasoning recorded at the ignore. It has no fix version — upstream considers
  side channels out of scope — and `ecdsa` is present only because `python-jose` declares it
  unconditionally; Crate never reaches it (local tokens HS256, suite tokens decoded with
  `algorithms=["RS256"]` pinned, so no EC signing/keygen/ECDH). Left un-ignored the job is red
  forever, which is how it went unexamined from 2026-07-27 to 2026-08-13 — a permanently red
  signal is no signal. Real remediation is replacing python-jose with PyJWT. Note the job runs
  `pip install -e .`, so it audits **runtime deps only**; dev-only advisories never gate it.
- `notify.yml` — **the first failure notification in any suite repo.** `workflow_run` on
  CI/Deploy/Release completing; when the conclusion is `failure` it pages ntfy `crate-alerts`
  with the run URL. Until it existed a red run was visible only to someone who went and looked,
  which is how the weekly `pip-audit` job stayed red from 2026-07-27 to 2026-08-13. Two design
  constraints worth keeping: (a) it must run on the **self-hosted** runner, because the suite's
  ntfy is tailnet-only on `:8095` and a GitHub-hosted runner cannot reach it — which is also why
  it is a separate workflow rather than an `if: failure()` step in `ci.yml`, since `ci.yml` has a
  `pull_request` trigger and invariant 7 forbids a self-hosted job being reachable from one;
  (b) every `github.event.workflow_run.*` value is passed through `env:` and never interpolated
  into the shell body — `workflow_run` fires for fork PRs too, with base-repo privileges, and a
  branch name is attacker-controlled text. The job is additionally gated on
  `head_repository.full_name == github.repository` so a fork cannot page (or reach) the prod host.
  A failed page is deliberately fatal: a notification that silently fails to send rebuilds the
  exact blind spot it was added to close. It cannot loop — "Notify" is absent from its own
  `workflows:` list, and `deploy.yml` watches `["CI"]` only.
- **Listing photo order.** `upload_photos_to_eps` sorts by `photo_role_rank` — front, back,
  detail, unknown, tag — rather than iterating `item.photos` in shoot order. eBay uses the
  first uploaded photo as the listing's gallery image, so before this whatever you happened to
  photograph first led the listing, and guided capture would have made that *worse* by
  encouraging tag shots. The tag is included but last: real size proof buyers want, just not a
  cover photo. Unknown-role photos share one rank and Python's sort is stable, so an item
  captured before roles uploads in exactly its original order — backward compatibility is
  structural rather than a special case. Presentation only; `ItemPhoto.order` is never
  rewritten, because the on-disk filenames derive from it. This is the one part of the roles
  feature CI verifies end to end, since eBay is always mocked at the transport.
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
   transport failure ⇒ `scan_error="identify_unavailable: …"` (also logged as a warning —
   an outage recorded only per-item in the DB is invisible in `docker logs`) — the draft
   always survives with its photos.
   **`_chat_vision` deliberately sends no `max_tokens`.** `google/gemma-4-e4b` is a
   reasoning model: it returns `reasoning_content` alongside `content`, and its hidden
   reasoning tokens share the completion budget while it emits nothing until reasoning
   finishes. An answer-sized cap would therefore return `""`, which `parse_identify` reads
   as "unidentifiable" — a silent, mocked-test-invisible failure (the suite-wide gemma-4
   trap). Confirmed live 2026-08-14: `content` is populated, ~15 s/item, inside the 60 s
   `lm_studio_timeout`.
   **The post-deploy smoke now runs this whole path.** `scripts/synthetic_smoke.py` used to stop
   at `/users/me`, so auth working was mistaken for Crate working and a deploy that broke rembg,
   cleanup or the LM Studio wiring shipped green. It now posts a generated PNG to `/items/scan`,
   polls for `processed_at`, asserts the photo came back `cleaned` and is servable, and always
   deletes the draft. It is strict about `identify_unavailable` (fails the deploy) and lenient
   about `low_confidence` (passes — a synthetic rectangle is legitimately unidentifiable, and
   that is a content outcome, not a config regression). The strictness is the point: a wrong
   `LM_STUDIO_BASE_URL` **or** `LM_STUDIO_VISION_MODEL` is the compose-env regression class that
   has bitten this suite twice, and both were confirmed to trip it. The test image is built from
   `zlib`+`struct` rather than Pillow because the smoke also runs inside the server container,
   whose image copies only `app/` and `alembic/` — `server/tests/` is not there.
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

## Photo roles + the label pass (2026-08-15)

`item_photos.role` (migration `0004`, nullable, `PHOTO_ROLES = front|back|detail|tag`) records
what each photo is a photo *of*. The client sends it as a `roles` form field on `POST
/items/scan`, index-aligned with `photos`; omitting it is valid and means unknown, which is
what keeps every pre-guided-capture caller working. Unlike vision output, an unrecognised role
is **rejected (422), not degraded** — it is a value our own client chose, so a bad one is a
contract bug. Role is never part of a filename: `photo_store` derives `original_{n}`/
`cleaned_{n}` from `order`, so cover-ness stays a derived property.

Three things the role buys, none of which `order` could answer:

- **The label pass.** `services/ai/label_prompts.py` + `read_label` in `vision.py`: one narrow
  call that reads only what is printed on a care label (size, size_type, material). It runs
  after identification, **before `signature_for_item`** — the clothing signature keys on brand
  AND size, so a size discovered later would silently disable the duplicate fast-path — and
  merges fill-never-overwrite. It is **best-effort with its own `except`**: allowed to reach the
  outer handler, a label-call 503 would rewrite a perfectly good identification as
  `identify_unavailable` and skip template matching and pricing. A failure logs a warning and
  sets no `scan_error`; size simply stays null, which already means "go read the tag".
- **Identification stops wasting a slot on the tag.** `MAX_IDENTIFY_PHOTOS` is 3 and read by
  order, so a tag shot fourth previously reached no model at all. Garment shots are preferred
  now, with tag photos as a fallback only if that is all there is.
- **The eBay hero image.** See "Listing photo order" below.

**Measured before shipping, three arms × three runs, against eight real tag photographs with
two negative controls** (a brand-only tab, a care-symbols-only label):

| arm | sizes read | controls kept clean |
|---|---|---|
| identify prompt on the cleaned photo (previous behaviour) | 3/18 | 6/6 |
| label prompt on the cleaned photo | 10/18 | 6/6 |
| **label prompt on the original photo (shipped)** | **15/18** | **6/6** |

So the narrow pass roughly quintuples recall and invented a size **zero times in 18 control
observations** — the bar a previous candidate prompt failed by confidently answering "M" for a
label whose "S" is circled. The circled-size-run rule in `LABEL_USER_PROMPT` handles that case
correctly now, and `test_label_prompts.py` asserts the guardrail strings literally, because a
silent edit softening them would reintroduce exactly that failure.

**Two corrections to the first published version of this table, both worth keeping as warnings.**

*The shipped arm was originally recorded as 12/18 because the ground truth was wrong.* One tag
was scored against the size in its source file's title (`大`) rather than against the label in
the photograph, which actually reads **別大** — two characters, "extra large" in hanbok sizing.
The model transcribed both, correctly, every time. A "strict" scorer added later then hard-coded
the mistake by explicitly rejecting `别大` as a garbled read of `大`. **Derive ground truth by
reading the image, never from a filename**, or a correct answer gets recorded as a failure and
the following weeks are spent fixing something that works.

*The remaining ~3/18 is not a fixed set of hard images.* Between measurement sessions results
are near-deterministic within a session but shift between them, and **which** photograph fails
moves — one session misses a jeans label, the next reads it and misses nothing else. So
cross-session comparisons of a few points are meaningless here; only same-session paired
comparisons are worth acting on.

**The pass reads the ORIGINAL, not the cleaned copy.** `clean_photo` is built for garments on
backgrounds and behaves unpredictably on a flat label — on one shirt it decided the woven brand
tab was "the subject" and cropped the garment away.

**A cleaned-copy retry when the original returns null was measured and rejected.** It does
recover the failing image — but 2 runs in 3, with the third returning `EU 36` for a label that
reads `EUR 30 / US 30 / CN 170/76A`. That trades a safe null for a wrong size one time in three,
which is the exact trade the never-infer rule exists to refuse. The retry also fires precisely
on labels that legitimately have no size (the negative controls), spending calls and adding
hallucination risk where there is nothing to find.

Honest limits: `tests/fixtures/images.py::tag_photo` carries no legible text, so CI proves
*routing* (which pass received which photo) and never OCR accuracy. Real accuracy is measured
with `scripts/photo_smoke.py`, which infers roles from filenames (`*-tag.jpg`) so a real
garment+tag pair can be pushed through a running server.

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

**Confirmed against the live stack, 2026-08-14.** The tests above prove the pipeline on
Pillow-built fixtures; CI can never exercise U2-Net (not downloaded) or a real vision model.
Driving 19 licensed real photographs through the deployed server closed both gaps: rembg
segmented 15 of 17 items to 4/4 pure-white corners with a tight crop (the two partials were a
clothing *rack* — no single subject — and a flat label), and the levels fix held on real
pixels, the dark-navy denim control landing at centre-mean `(72,77,87)` on pure white with
**0.03% pure black** where the old order produced `(0,0,0)`.

**Size reading: measured, and a prompt "improvement" rejected on the evidence.** Ground truth
was read by eye off 8 real tag photographs and replayed through the shipping
`build_identify_messages`/`parse_identify` three times. The current prompt scored **24/24 on
safety — it never invented a size** — while transcribing only ~1/6 of legible ones. A candidate
that added "reading is not inferring" plus a rule for marked size runs gave **no recall gain and
a reproducible wrong answer** (`M` for a label whose `S` is circled, 3 runs of 3). It was not
shipped. Direct probing shows the model *can* read these tags when asked plainly, so the recall
gap is real — but it must not be closed by softening the never-infer rule, because the first
nudge in that direction immediately started guessing the middle of a size run. Under-reading is
the designed trade: a null sends a human to the tag; a wrong size ships the wrong garment.

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
- **It must stay Windows PowerShell 5.1-compatible** — that is the host's `powershell.exe`
  and what the nightly scheduled task runs; there is no `pwsh` on the Dragonfly host. As
  first written it used `Set-Content -AsByteStream` (PowerShell 7+ only) for the dump, so
  under 5.1 it threw immediately and left an empty timestamped directory — present in a
  listing, worthless on restore, exactly the "trusted empty backup" this script exists to
  prevent. The dump is now redirected by `cmd` straight to disk: binary must never travel
  through a 5.1 pipeline, which decodes it to text and corrupts it, and the 5.1 spelling
  (`-Encoding Byte`) is no better since it is gone in 7. Verified 2026-08-14 against the
  live stack (`PGDMP` header, `pg_restore --list` reads 55 TOC entries).
- **The byte floor does not apply to a legitimately empty archive.** `$MinPhotosBytes` (100)
  exists to catch a truncated tar, but an empty gzipped tar is ~45 bytes, so a Crate with no
  items yet failed its backup on *every* run until the first scan. A job that cries wolf nightly
  is how a real alarm gets ignored. The floor is now skipped when the photo-row count is **known
  to be zero**; `-1` (count query failed) still enforces it, and the files-vs-rows cross-check
  is unchanged. Found by running the backup right after emptying the archive, not by reading it.
- **Scheduling, encryption, NAS delivery and retention live in `C:\Scripts`, not here.** The host
  convention is that repo scripts produce a verified set and `C:\Scripts` promotes it:
  `Backup-CrateArchive.ps1` (scheduled task "Crate Archive Backup", daily 04:30, offset from the
  03:30 DB backup and 04:00 media-config backup) invokes this script into a temp staging dir,
  gpg-encrypts `db.dump` and `photos.tar.gz` with the same key material as
  `Backup-DragonflyDatabases.ps1`, and copies them to `\\Diskstation\Media2\Backups\Crate\` with
  a 30-day prune. `MANIFEST.json` is promoted **in clear** on purpose so a freshness check can
  read a set's age without the passphrase. Note the nightly `Dragonfly DB Backup` covers Crate's
  *database* but is pg_dump-only and has never touched a Docker volume — before this task the
  photos, which for a wardrobe archive are the actual artifact, had no backup at all.

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
- **A failed publish is resumable.** `publish_item` commits after eBay has created the
  photos, inventory item and offer, *before* attempting the publish that can fail — the
  router only commits on success, so without it a failed publish rolled back the offer id
  and every photo's EPS url while eBay kept both. The next attempt then re-uploaded every
  image and collided with errorId 25002. If it does collide, `_existing_offer_id` recovers
  the id from the error's `offerId` parameter (not its message text, which eBay rewords) and
  adopts it. This stranded offer 11447191010 on the first real post and needed a hand-written
  UPDATE to recover.
- **Placeholder condition notes never reach a listing.** Vision models answer "no condition
  notes" with `"N/A"` rather than by omitting the field, so the first real listing shipped
  with the line "Condition: N/A" visible to buyers. `scan_pipeline._is_placeholder` drops
  the known placeholder set before composing the description.
- **Review-stage dropdowns** (`routers/meta.py`, `services/ebay/taxonomy.py`, client
  `DropdownField`). The fields eBay refuses a listing without are chosen by a human, not
  guessed: Condition, eBay category, and — for clothing — Department and Size Type.
  Vocabularies are served from `apparel/attributes.py` rather than duplicated in Kotlin (a
  hardcoded copy drifts into 422s the user cannot act on), labels included, because
  `big_tall` is a wire value and "Big & Tall" is what a person picks.
  Category options come from **eBay's taxonomy API, never the vision model**: ids are eBay's,
  versioned (tree v134 today), and a hallucinated one fails at publish. Gemma supplies the
  words; eBay supplies the id. Suggestions load on menu-open, not per scan — each is a live
  call and most drafts in a batch are never expanded. `readyToPost()` mirrors
  `sell._require_ready` so the button is not *offered* on an incomplete draft, kept in step
  by `ReviewGatingTest`.
- **Apparel item specifics** (`apparel_aspects()`). `attributes.py` deferred this mapping
  until a keyset existed rather than guess eBay's strings; the values are now checked
  against a live `get_item_aspects_for_category` call. eBay *requires* Brand, Color, Size,
  Size Type and Department on a clothing listing, and enforces it at **publish** — i.e.
  after EPS photos, the inventory item and the offer already exist. `_require_ready` checks
  them up front so the failure is a 422 naming the gaps instead of a half-built listing
  stranded on eBay. Unknown values are omitted, never defaulted: an item specific is a claim
  a buyer pays against, and an unrecognised enum is dropped rather than passed through raw.
- **Apparel conditions are a separate vocabulary** (`ebay_condition()`). eBay's clothing
  categories accept the "new" grades plus a *single* used grade (3000, "Pre-owned"); a
  garment published as `USED_GOOD` is rejected with errorId 25059. So `like_new|good|fair|
  poor` all collapse to `USED_EXCELLENT` for `item_kind == "clothing"`, and the description
  carries the nuance. The collapse is one-directional by design: mapping `like_new` up to
  `NEW_WITHOUT_TAGS` would preserve granularity but assert to a buyer that the garment was
  never worn, which Crate will not claim on a used item's behalf. Tested in both directions,
  including that an unknown condition falls back to a used grade rather than a new one.
- Honest error surfaces: 503 keyset unconfigured / 409 not-connected or policies
  missing / 502 eBay rejected (with eBay's message excerpt).
- Client: Settings screen (connection status + one-time consent via browser + sign
  out); review cards gain "Post to eBay" (enabled only with title + chosen price).

**Consent, hardened after first live contact (2026-08-15).** The flow above was born mocked
and its first real run failed six straight times: eBay rendered consent, the user accepted,
and the redirect arrived at `/ebay/callback` with **no query string at all**. The audit
exonerated everything local (query strings survive Tailscale Serve; the 422 body proved the
request reached FastAPI; no middleware touches queries) and found two authorize-call gaps,
both now fixed:

- **`prompt=login` is mandatory in `authorize_url`.** Without it, eBay treats an
  already-granted keyset as "nothing to ask" and redirects WITHOUT a code — so the very
  first accept poisons every retry. Consent is once per ~18 months; always re-prompting
  costs nothing. `test_ebay_oauth.py` asserts the param as a guardrail string.
- **The base `https://api.ebay.com/oauth/api_scope` leads `USER_SCOPES`** — the one scope
  every keyset holds, present in eBay's own generated consent URLs.
- **`scripts/ebay_manual_consent.py` is the redirect-independent path**: leave the RuName's
  accepted URL blank, eBay lands on its own success page whose URL carries the code, paste
  it to the script (`docker compose cp` in first — the image doesn't ship scripts/), which
  calls `exchange_code` directly. `state` binds a browser redirect to a session; there is
  no redirect here, so none is needed. Legitimate as a *permanent* flow for a single-user
  app, and immune to however eBay feels about a `:8446` callback URL.
- A bare callback now renders a **human HTML page** (what happened, what to do) instead of
  raw 422 JSON, and logs a warning naming the situation.
- **`scripts/ebay_store_token.py` — the path with no redirect in it.** After eleven
  attempts (consent granted each time, confirmed with the owner), the callback still
  receives nothing: no query, no fragment. eBay's redirect builder is broken for this
  RuName, so the code half of the flow is unreachable and no retry will change that. eBay's
  developer portal issues a user token directly for single-account apps
  (**Get a User Token Here → OAuth → Sign in to Sandbox**); this script stores what that
  page prints, the way `exchange_code` would have. When the portal surfaces no refresh
  token, `refresh_expires_at` is set equal to `expires_at` rather than a fictitious 18
  months — so `/ebay/status` stays honest and `user_token()` raises its reconnect 409
  instead of attempting a refresh that cannot succeed.
- **The fragment probe.** Nine identical bare callbacks cannot distinguish "eBay sent no
  code" from "eBay sent the code after a `#`" — a URL fragment never leaves the browser, so
  the server sees the same bare GET either way. The bare page therefore ships a few lines of
  JS that bounce the whole landed URL back as `?probe=…`, which lands in the access log and
  the warning log. It fires only when a fragment exists, the bounce target carries none, and
  `probe` short-circuits the branch that serves the script — loop-safe twice over. The value
  is attacker-supplied text on an unauthenticated route: logged truncated, never stored.

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
