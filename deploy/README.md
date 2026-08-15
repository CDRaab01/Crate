# Crate deploy (self-hosted runner, tailnet-only)

Operational model cloned from Cookbook/Spotter (see their `deploy/README.md` for the
long-form runner guide). Crate-specific facts:

- **Host ports:** API `127.0.0.1:8007`, Postgres `127.0.0.1:5438`.
- **No tunnel.** Crate is tailnet-only: expose it with Tailscale Serve on the host
  (planned Serve port **8446** — 443/8443/8445 are taken by Magpie/Hawksnest/Remnant).
  Record the final ts.net URL in CLAUDE.md + ARCHITECTURE.md, point the eBay RuName's
  accept URL at `https://<ts.net>:8446/ebay/callback`, and set `CRATE_SERVER_URL`
  (GitHub Actions variable) so CI builds bake the right default server URL.
- **Runner:** register a self-hosted runner with the `crate` label; set the `CRATE_DIR`
  Actions variable to the canonical clone path. `deploy/redeploy.ps1` is the single
  redeploy entrypoint (fetch → reset → compose up → /health gate on 8007 → prune).
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
  (`/data/photos` — item photo binaries; the DB stores paths only). Surviving a redeploy
  is *not* a backup — see below.

## Backups

Named volumes survive `docker compose up`, but not `down -v`, a dead disk, or a host
rebuild. Crate's registry is the only record of items that have been photographed,
measured and boxed, so run `deploy/backup.ps1` on the host:

```powershell
# One-off, to other physical media (a NAS share, an external drive):
powershell deploy/backup.ps1 -BackupDir \\nas\backups\crate

# Or set CRATE_BACKUP_DIR once and just run it:
powershell deploy/backup.ps1

# Nightly at 02:30 (needs Docker Desktop running; runs as the interactive user):
schtasks /create /tn "Crate backup" /sc daily /st 02:30 /tr ^
  "powershell -NoProfile -ExecutionPolicy Bypass -File C:\Code\Crate\deploy\backup.ps1"
```

Each run writes `<BackupDir>\crate-YYYYMMDD-HHmmss\` containing `db.dump`,
`photos.tar.gz` and `MANIFEST.json`, verifies them, and prunes to `-Keep` (default 14)
*only after* the new set verifies — a failing run never deletes the last good backup.
`powershell deploy/backup.ps1 -Verify` re-checks the newest set; use it to confirm a
scheduled job is really producing restorable output rather than silently writing stubs.

**On the Dragonfly host this is already scheduled — don't set up a second one.**
`C:\Scripts\Backup-CrateArchive.ps1` (task "Crate Archive Backup", daily 04:30) calls this
script into a temp staging dir, gpg-encrypts `db.dump` and `photos.tar.gz`, and promotes them
to `\\Diskstation\Media2\Backups\Crate\` with a 30-day prune; `MANIFEST.json` goes up in clear
so `Test-SuiteInvariants.ps1` can check a set's age without the passphrase. The `schtasks`
recipe above is for a *different* host, or as a reference. Note the nightly `Dragonfly DB
Backup` already covers Crate's database — it is pg_dump-only and never touches a Docker volume,
so the photos are what this adds.

The script runs under **Windows PowerShell 5.1** — the host's `powershell.exe` and what the
scheduled task above gets (there is no `pwsh` on the Dragonfly host). Keep it 5.1-compatible:
it originally wrote the dump with `Set-Content -AsByteStream`, which is PowerShell 7+ only, so
under 5.1 it threw on its first step and left an **empty** backup directory behind — a set that
looks present in a listing until you open it. That is why `-Verify` exists; run it after any
change here, under `powershell -NoProfile -File …` rather than an interactive 7 shell.

### Restoring from a backup

Restore is not exercised by CI, so **rehearse it once against a throwaway Compose project
before you need it.** With the stack running and `$Set` pointing at a backup folder:

```powershell
$Set = "\\nas\backups\crate\crate-20260812-023000"

# 1. Database. --clean --if-exists drops the existing objects first, so this REPLACES
#    current data. Stop the server container so nothing writes mid-restore.
docker compose stop server
Get-Content "$Set\db.dump" -AsByteStream |
  docker compose exec -T db pg_restore -U crate -d crate --clean --if-exists
docker compose start server

# 2. Photos, back into the volume the server container mounts.
$serverId = docker compose ps -q server
docker run --rm --volumes-from $serverId -v "${Set}:/backup:ro" postgres:16 `
  sh -c "rm -rf /data/photos/* && tar xzf /backup/photos.tar.gz -C /data/photos"
```

Then confirm: `GET /health` is ok, `GET /version` reports `Crate API`, and an item's
photo endpoint (`/items/{id}/photos/{pid}/file`) returns a real image — that last check is
the one that proves the DB paths and the restored binaries line up.

A restore onto a **newer** schema is fine: migrations run on container boot, so restore
first, then let the entrypoint's `alembic upgrade head` catch the data up. Restoring a
*newer* dump onto older code is not supported — check `MANIFEST.json`'s
`deployed_commit` if the two might disagree.
