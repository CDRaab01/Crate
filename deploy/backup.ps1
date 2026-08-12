<#
.SYNOPSIS
  Back up Crate's database and item photos to a destination outside Docker (Windows /
  Docker Desktop).

.DESCRIPTION
  Crate's data lives in two Docker named volumes (pgdata, photos). Those survive
  redeploys -- that is all docker-compose.yml claims -- but they do NOT survive
  `docker compose down -v`, a disk failure, or a host rebuild. This script is the
  actual backup: it writes a self-contained, timestamped set to a path you choose,
  which should be on different physical media (a NAS share, an external drive, a
  synced folder). A "backup" sitting on the same disk as the volume it copies is a
  copy, not a backup.

  This matters more for Crate than for the other suite apps. Its registry is the only
  record of a wardrobe that has been photographed, tagged, measured and boxed; the
  garments themselves get sealed in bins for months while the eBay keyset is pending.
  Losing the DB means unboxing everything and starting over, and losing the photos
  means re-shooting items that may no longer be reachable.

  Each run produces:
    <BackupDir>\crate-YYYYMMDD-HHmmss\
      db.dump        - pg_dump custom format (-Fc), restore with pg_restore
      photos.tar.gz  - the /data/photos volume, gzipped tar
      MANIFEST.json  - sizes, counts, deployed commit, and the verification result

  The script VERIFIES what it wrote before reporting success: a backup that silently
  produces empty archives is worse than no backup, because it is trusted. It checks
  that both artifacts are non-trivially sized and that the photo archive holds at
  least one file per item_photos row (originals are written to disk before their row
  is committed, so files >= rows always holds on a consistent set).

  Restore instructions live in deploy/README.md ("Restoring from a backup").

.PARAMETER BackupDir
  Where to write the timestamped backup folder. Point this at other physical media.
  Defaults to the CRATE_BACKUP_DIR environment variable, else <repo>\..\crate-backups.

.PARAMETER Keep
  How many timestamped backup folders to retain; older ones are deleted after a
  successful run. Defaults to 14. Pass 0 to disable pruning.

.PARAMETER SkipPhotos
  Back up the database only. Useful for a quick pre-migration snapshot; the photo
  archive is the slow part.

.PARAMETER Verify
  Verify the most recent existing backup in -BackupDir and exit without writing a new
  one. Use this to confirm a scheduled job is really producing restorable sets.

.EXAMPLE
  powershell deploy/backup.ps1 -BackupDir \\nas\backups\crate

.EXAMPLE
  powershell deploy/backup.ps1 -Verify

.EXAMPLE
  # Nightly at 02:30, as the interactive user (needs Docker Desktop running):
  schtasks /create /tn "Crate backup" /sc daily /st 02:30 /tr ^
    "powershell -NoProfile -ExecutionPolicy Bypass -File C:\Code\Crate\deploy\backup.ps1"
#>
[CmdletBinding()]
param(
  [string]$BackupDir = $(if ($env:CRATE_BACKUP_DIR) { $env:CRATE_BACKUP_DIR } else { "" }),
  [int]$Keep = 14,
  [switch]$SkipPhotos,
  [switch]$Verify
)

$ErrorActionPreference = "Stop"

# Repo root = parent of this script's directory (deploy/), same resolution as redeploy.ps1
# so the script operates on the real deployment clone that owns the volumes.
$RepoDir = Split-Path -Parent $PSScriptRoot
if (-not $BackupDir) {
  $BackupDir = Join-Path (Split-Path -Parent $RepoDir) "crate-backups"
}

# Smallest plausible artifact sizes. A pg_dump of an empty-but-migrated schema is a few KB;
# anything under this means the dump failed and left a stub. The gzip of an empty tar is
# about 45 bytes, so 100 catches "wrote nothing" without tripping on a genuinely empty
# photo set (a fresh deploy before the first capture).
$MinDumpBytes = 1024
$MinPhotosBytes = 100

function Invoke-Checked {
  param([string]$Exe, [string[]]$ArgList)
  Write-Host "> $Exe $($ArgList -join ' ')"
  & $Exe @ArgList
  if ($LASTEXITCODE -ne 0) {
    throw "Command failed ($LASTEXITCODE): $Exe $($ArgList -join ' ')"
  }
}

function Get-ComposeEnvValue {
  # Reads a variable from the deployment clone's root .env (the same file Compose reads
  # for POSTGRES_USER/POSTGRES_DB), falling back to the compose default.
  param([string]$Name, [string]$Default)
  $envPath = Join-Path $RepoDir ".env"
  if (Test-Path $envPath) {
    $line = Select-String -Path $envPath -Pattern "^\s*$Name\s*=" -ErrorAction SilentlyContinue |
      Select-Object -First 1
    if ($line) {
      $value = ($line.Line -split "=", 2)[1].Trim().Trim('"').Trim("'")
      if ($value) { return $value }
    }
  }
  return $Default
}

function Get-BackupSets {
  if (-not (Test-Path $BackupDir)) { return @() }
  return @(Get-ChildItem -Path $BackupDir -Directory -Filter "crate-*" |
    Sort-Object Name -Descending)
}

function Test-BackupSet {
  # Returns a result object rather than throwing, so both the write path and -Verify can
  # report the same detail.
  param([string]$SetPath, [int]$ExpectedPhotoRows = -1)

  $dumpPath = Join-Path $SetPath "db.dump"
  $photosPath = Join-Path $SetPath "photos.tar.gz"
  $problems = @()
  $warnings = @()

  if (-not (Test-Path $dumpPath)) {
    $problems += "db.dump is missing"
  } else {
    $dumpBytes = (Get-Item $dumpPath).Length
    if ($dumpBytes -lt $MinDumpBytes) {
      $problems += "db.dump is only $dumpBytes bytes - the dump did not complete"
    }
  }

  $photoFiles = -1
  if (-not (Test-Path $photosPath)) {
    # A missing archive is only legitimate when the set was deliberately taken with
    # -SkipPhotos, which the manifest records. Without that, photos.tar.gz being absent is
    # exactly the silent-empty-backup failure this function exists to catch.
    $manifestPath = Join-Path $SetPath "MANIFEST.json"
    $photosExpected = $true
    if (Test-Path $manifestPath) {
      try {
        $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
        $photosExpected = [bool]$manifest.photos_included
      } catch {
        $problems += "MANIFEST.json is unreadable"
      }
    }
    if ($photosExpected) {
      $problems += "photos.tar.gz is missing and the set was not taken with -SkipPhotos"
    }
  } else {
    $photoBytes = (Get-Item $photosPath).Length
    if ($photoBytes -lt $MinPhotosBytes) {
      $problems += "photos.tar.gz is only $photoBytes bytes - the archive did not complete"
    } else {
      # Count entries from inside a container: Windows has no tar that reads gzip reliably
      # across PowerShell versions, and this keeps the tooling requirement to Docker alone.
      # postgres:16 (not alpine) because the host already has it pulled for the db service,
      # so verification never needs a registry round trip and works on an offline host.
      # A dead Docker daemon and a corrupt archive both surface as exit 1 from
      # `docker run`, so the daemon is probed separately: only once it is known good can a
      # failed listing be blamed on the archive. Getting this backwards would either
      # condemn good backups or bless corrupt ones. Inside the container, tar failure is
      # reported as exit 3 (a pipeline would otherwise mask it behind wc's exit 0).
      $mount = "${SetPath}:/backup:ro"
      $listCmd = 'tar tzf /backup/photos.tar.gz > /tmp/l || exit 3; grep -v "/$" /tmp/l | wc -l'
      $counted = & docker run --rm -v $mount postgres:16 sh -c $listCmd 2>$null
      $listExit = $LASTEXITCODE

      if ($listExit -eq 0 -and $counted) {
        $photoFiles = [int]($counted.Trim())
        if ($ExpectedPhotoRows -ge 0 -and $photoFiles -lt $ExpectedPhotoRows) {
          # Every item_photos row has its original on disk before the row is committed,
          # so fewer files than rows means the archive is missing real data.
          $problems += "photos.tar.gz holds $photoFiles files but the database has $ExpectedPhotoRows photo rows - originals are missing"
        }
      } elseif ($listExit -eq 3) {
        $problems += "photos.tar.gz could not be read by tar - the archive is corrupt"
      } else {
        & docker version --format '{{.Server.Version}}' 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
          # Docker itself is unusable here; that says nothing about the archive, so it must
          # not condemn a set that may be perfectly good.
          $warnings += "could not run the archive check (Docker unavailable); photos.tar.gz was written but not listed"
        } else {
          $problems += "photos.tar.gz could not be listed (docker exit $listExit) - treat this set as suspect"
        }
      }
    }
  }

  return [pscustomobject]@{
    Ok         = ($problems.Count -eq 0)
    Problems   = $problems
    Warnings   = $warnings
    PhotoFiles = $photoFiles
  }
}

# --- Verify mode: check the newest existing set and exit ---------------------------------
if ($Verify) {
  Write-Host "=== Crate backup verify ==="
  Write-Host "Backups: $BackupDir"
  $sets = Get-BackupSets
  if ($sets.Count -eq 0) {
    throw "No backups found in $BackupDir. Run deploy/backup.ps1 first."
  }
  $newest = $sets[0]
  Write-Host "Newest:  $($newest.Name)"
  $result = Test-BackupSet -SetPath $newest.FullName
  foreach ($w in $result.Warnings) { Write-Host "WARN: $w" }
  if (-not $result.Ok) {
    foreach ($p in $result.Problems) { Write-Host "FAIL: $p" }
    throw "Backup $($newest.Name) is not restorable."
  }
  Write-Host "Verified: db.dump and photos.tar.gz are present and readable ($($result.PhotoFiles) photo files)."
  Write-Host "=== Verify complete ==="
  return
}

# --- Write a new backup ------------------------------------------------------------------
Write-Host "=== Crate backup ==="
Write-Host "Repo:    $RepoDir"
Write-Host "Backups: $BackupDir"

$pgUser = Get-ComposeEnvValue -Name "POSTGRES_USER" -Default "crate"
$pgDb = Get-ComposeEnvValue -Name "POSTGRES_DB" -Default "crate"

# The db container must be up: pg_dump runs inside it, and a dump taken from a stopped
# stack would silently be nothing at all.
$dbContainer = (& docker compose --project-directory $RepoDir ps -q db 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $dbContainer) {
  throw "The crate db container is not running. Start the stack first: docker compose --project-directory $RepoDir up -d"
}

$stamp = (Get-Date).ToString("yyyyMMdd-HHmmss")
$setPath = Join-Path $BackupDir "crate-$stamp"
New-Item -ItemType Directory -Path $setPath -Force | Out-Null

# 1. Database. Custom format (-Fc) so pg_restore can do selective/parallel restores, and
#    so the dump is compressed without a second tool.
$dumpPath = Join-Path $setPath "db.dump"
Write-Host "Dumping database '$pgDb'..."
& docker compose --project-directory $RepoDir exec -T db pg_dump -U $pgUser -d $pgDb -Fc |
  Set-Content -Path $dumpPath -AsByteStream
if ($LASTEXITCODE -ne 0) {
  throw "pg_dump failed - no backup written."
}

# 2. Photos. --volumes-from borrows the server container's mounts, so the volume's
#    Compose-project-prefixed name never has to be guessed here.
$photoRows = -1
if ($SkipPhotos) {
  Write-Host "Skipping photos (-SkipPhotos)."
} else {
  $serverContainer = (& docker compose --project-directory $RepoDir ps -q server 2>$null)
  if (-not $serverContainer) {
    throw "The crate server container is not running, so its photos volume cannot be read. Start the stack first."
  }
  Write-Host "Archiving item photos..."
  $mount = "${setPath}:/backup"
  Invoke-Checked docker @(
    "run", "--rm", "--volumes-from", $serverContainer, "-v", $mount,
    "alpine", "tar", "czf", "/backup/photos.tar.gz", "-C", "/data/photos", "."
  )

  # Expected file floor, for the verification below.
  $countText = (& docker compose --project-directory $RepoDir exec -T db `
      psql -U $pgUser -d $pgDb -t -A -c "select count(*) from item_photos" 2>$null)
  if ($LASTEXITCODE -eq 0 -and $countText) { $photoRows = [int]($countText.Trim()) }
}

# 3. Verify before claiming success.
Write-Host "Verifying..."
$result = Test-BackupSet -SetPath $setPath -ExpectedPhotoRows $photoRows
foreach ($w in $result.Warnings) { Write-Host "WARN: $w" }
if (-not $result.Ok) {
  foreach ($p in $result.Problems) { Write-Host "FAIL: $p" }
  throw "Backup verification failed. The set at $setPath is NOT restorable; the previous backup is untouched."
}

# 4. Manifest. Records what this set contains and what was running when it was taken, so a
#    restore months from now does not have to guess at the schema version.
$deployedSha = "unknown"
try { $deployedSha = (& git -C $RepoDir rev-parse --short HEAD).Trim() } catch { }
$dumpBytes = (Get-Item $dumpPath).Length
$photoBytes = if (Test-Path (Join-Path $setPath "photos.tar.gz")) {
  (Get-Item (Join-Path $setPath "photos.tar.gz")).Length
} else { 0 }

[pscustomobject]@{
  taken_at        = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
  deployed_commit = $deployedSha
  database        = $pgDb
  db_dump_bytes   = $dumpBytes
  photos_bytes    = $photoBytes
  photo_files     = $result.PhotoFiles
  photo_rows      = $photoRows
  photos_included = (-not $SkipPhotos)
} | ConvertTo-Json | Set-Content -Path (Join-Path $setPath "MANIFEST.json") -Encoding utf8

$dumpMb = [math]::Round($dumpBytes / 1MB, 2)
$photoMb = [math]::Round($photoBytes / 1MB, 2)
Write-Host "Wrote $setPath (db ${dumpMb} MB, photos ${photoMb} MB, $($result.PhotoFiles) photo files)."

# 5. Prune old sets - only after a verified-good new one exists, so a failing run can
#    never delete the last good backup.
if ($Keep -gt 0) {
  $sets = Get-BackupSets
  if ($sets.Count -gt $Keep) {
    foreach ($old in $sets[$Keep..($sets.Count - 1)]) {
      Write-Host "Pruning old backup $($old.Name)"
      Remove-Item -Path $old.FullName -Recurse -Force
    }
  }
}

Write-Host "=== Backup complete ==="
