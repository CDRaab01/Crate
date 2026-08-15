"""Post-deploy synthetic smoke for Crate (SSO-only, Magpie pattern).

Crate has no register/login endpoints, so the smoke mints an aud="suite" token from
dragonfly-id's POST /smoke/token using a confidential smoke credential, trades it at Crate's
POST /auth/suite, and exercises an authenticated read. Proves: the identity server trusts us,
Crate's JWKS validation + find-or-create works, and the DB is reachable — not just that
/health is up.

It then runs one photo through POST /items/scan. Auth working is not the same as Crate
working: for its first months this smoke passed while never touching the pipeline the whole
app exists for, so a deploy that broke rembg, cleanup or the LM Studio wiring shipped green.
The scan stage is deliberately strict about `identify_unavailable` — a wrong
LM_STUDIO_BASE_URL is exactly the compose-env regression that has bitten this suite twice
(see the §2 rule in CLAUDE.md), and nothing else would catch it.

Config (env):
  CRATE_URL                 Crate base URL       (default http://127.0.0.1:8007)
  SMOKE_TOKEN_URL           dragonfly-id smoke endpoint
                            (default https://id.dragonflymedia.org/smoke/token)
  CRATE_SMOKE_CLIENT_ID     smoke client id      (default crate-smoke)
  CRATE_SMOKE_CLIENT_SECRET smoke client secret  (required — from the deployed .env)
  SMOKE_EMAIL               allowlisted subject  (default crate-smoke@dragonflymedia.org;
                            must be in dragonfly-id's SMOKE_SUBJECT_EMAILS)
  SMOKE_SCAN                set to 0 to skip the scan stage (auth-only, the old behaviour)
  SMOKE_SCAN_TIMEOUT        seconds to wait for the draft to process (default 180)

Exit 0 + "SMOKE_PASS" on success; exit 1 with [FAIL] otherwise. Stdlib only — it runs inside
the server container, where server/tests/ does not exist (the image copies only app/ and
alembic/), so the Pillow fixtures in tests/fixtures/images.py are unavailable and the test
image is built here from zlib + struct instead.
"""

import json
import os
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib

CRATE_URL = os.environ.get("CRATE_URL", "http://127.0.0.1:8007").rstrip("/")
SMOKE_TOKEN_URL = os.environ.get(
    "SMOKE_TOKEN_URL", "https://id.dragonflymedia.org/smoke/token"
)
CLIENT_ID = os.environ.get("CRATE_SMOKE_CLIENT_ID", "crate-smoke")
CLIENT_SECRET = os.environ.get("CRATE_SMOKE_CLIENT_SECRET", "")
SMOKE_EMAIL = os.environ.get("SMOKE_EMAIL", "crate-smoke@dragonflymedia.org")
SCAN_ENABLED = os.environ.get("SMOKE_SCAN", "1") != "0"
SCAN_TIMEOUT = int(os.environ.get("SMOKE_SCAN_TIMEOUT", "180"))


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    sys.exit(1)


def decode_body(raw: bytes) -> dict:
    """Decode a response body without assuming it is JSON.

    Error responses often aren't: a proxy or gateway in front of the identity server answers with
    an HTML page, and json.loads()ing that turns a diagnosable failure (a status code plus a page
    saying what broke) into an opaque JSONDecodeError traceback. Non-JSON bodies come back under
    "_raw" so the caller's "returned {status}: {body}" message still says something useful.
    """
    text = raw.decode(errors="replace").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except ValueError:
        return {"_raw": " ".join(text.split())[:200]}
    if isinstance(parsed, dict):
        return parsed
    # A JSON array is valid and expected (GET /items returns one), but it is not a mapping and
    # every caller does .get(). It used to be stringified into "_raw" with repr() and truncated
    # at 200 chars, which quietly made list endpoints unreadable rather than merely awkward —
    # the data was there and then thrown away. Hand it back intact under a key instead.
    if isinstance(parsed, list):
        return {"_list": parsed}
    # A bare scalar really is unusable; keep it printable for the failure message.
    return {"_raw": str(parsed)[:200]}


def request(method: str, url: str, *, form=None, body=None, token=None, timeout=15):
    # Identify ourselves. urllib's default UA ("Python-urllib/3.x") is a known bot signature, and
    # a CDN in front of any endpoint this script talks to can reject it outright — Cloudflare
    # answered "error code: 1010" (403) to exactly that, before the request reached the app.
    headers = {"User-Agent": "crate-synthetic-smoke/1.0"}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, decode_body(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, decode_body(e.read())
    except Exception as e:  # noqa: BLE001 — a smoke failure reason is always worth printing
        fail(f"{method} {url}: {e}")


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def make_test_png(width: int = 320, height: int = 400) -> bytes:
    """A dark rectangle on a light ground, as an 8-bit truecolour PNG.

    Deliberately a *subject on a background* rather than a flat fill, so the cleanup stage has
    something to segment and crop to instead of degrading straight to the Pillow-only path.
    Built by hand because this script must stay stdlib-only: it runs inside the server
    container, which has Pillow but not server/tests/, and on hosts whose python may have
    neither.
    """
    bg, fg = b"\xf0\xf0\xf0", b"\x28\x3c\x78"
    x0, x1 = width // 4, width - width // 4
    y0, y1 = height // 5, height - height // 5
    plain = bg * width
    subject = bg * x0 + fg * (x1 - x0) + bg * (width - x1)

    raw = bytearray()
    for y in range(height):
        raw.append(0)  # per-scanline filter: None
        raw += subject if y0 <= y < y1 else plain

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _png_chunk(b"IEND", b"")
    )


def post_photo(url: str, token: str, filename: str, blob: bytes, timeout: int = 60):
    """POST one in-memory image as multipart/form-data under the "photos" field.

    Hand-rolled because `request` above only speaks urlencoded/JSON and the stdlib has no
    multipart writer. Mirrors post_photos() in photo_smoke.py, minus the filesystem.
    """
    boundary = f"----crate{uuid.uuid4().hex}"
    body = bytearray()
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="photos"; filename="{filename}"\r\n'.encode()
    body += b"Content-Type: image/png\r\n\r\n"
    body += blob
    body += f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        url,
        data=bytes(body),
        method="POST",
        headers={
            "User-Agent": "crate-synthetic-smoke/1.0",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, decode_body(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, decode_body(e.read())
    except Exception as e:  # noqa: BLE001
        fail(f"POST {url}: {e}")


def fetch_bytes(url: str, token: str, timeout: int = 30):
    """GET raw bytes (the photo endpoint serves binary, not JSON)."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "crate-synthetic-smoke/1.0", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:  # noqa: BLE001
        fail(f"GET {url}: {e}")


def run_scan_check(access: str) -> None:
    """Push one generated photo through the real pipeline and assert it came out the far end.

    Asserts the deploy, not the model's taste. A synthetic rectangle is not a recognisable
    product, so "low_confidence" is a correct outcome and passes; what must not happen is the
    pipeline failing to run, or the vision transport being unreachable.
    """
    status, body = post_photo(
        f"{CRATE_URL}/items/scan", access, "smoke.png", make_test_png()
    )
    if status != 202 or "id" not in body:
        fail(f"/items/scan returned {status}: {body}")
    item_id = body["id"]

    try:
        deadline = time.time() + SCAN_TIMEOUT
        item: dict = {}
        while time.time() < deadline:
            status, item = request("GET", f"{CRATE_URL}/items/{item_id}", token=access)
            if status == 200 and item.get("processed_at"):
                break
            time.sleep(2)
        else:
            fail(
                f"scan draft {item_id} still unprocessed after {SCAN_TIMEOUT}s — the background "
                f"task is wedged, or the vision call is hanging under the {SCAN_TIMEOUT}s budget"
            )

        scan_error = item.get("scan_error") or ""
        if scan_error.startswith("identify_unavailable"):
            fail(
                f"scan reached the pipeline but identification was unreachable: {scan_error}\n"
                f"  The server could not talk to LM Studio. Inside the container localhost is\n"
                f"  the container: LM_STUDIO_BASE_URL must be http://host.docker.internal:1234/v1\n"
                f"  (pinned in docker-compose.yml's environment: block, NOT env_file — Compose\n"
                f"  does not re-read env_file on recreate). Check GET :1234/v1/models for the\n"
                f"  model actually loaded; it must match LM_STUDIO_VISION_MODEL."
            )
        if scan_error and scan_error != "low_confidence":
            fail(f"scan finished with scan_error={scan_error!r}")

        photos = item.get("photos") or []
        if not photos:
            fail(f"draft {item_id} came back with no photo rows")
        if not photos[0].get("cleaned"):
            fail(
                "the photo was stored but never cleaned — clean_photo did not run. "
                "rembg/Pillow degrade paths should still mark it cleaned, so this is a "
                "pipeline break, not a segmentation miss."
            )

        status, blob = fetch_bytes(
            f"{CRATE_URL}/items/{item_id}/photos/{photos[0]['id']}/file", access
        )
        if status != 200 or len(blob) < 512:
            fail(f"cleaned photo fetch returned {status} with {len(blob)} bytes")

        note = " (low_confidence — expected for a synthetic shape)" if scan_error else ""
        print(f"scan OK: draft processed, photo cleaned, {len(blob)} bytes served{note}")
    finally:
        # Always clean up, including after fail() — sys.exit raises, so this still runs. The
        # smoke runs on every deploy; leaving drafts behind would accumulate forever in prod.
        request("DELETE", f"{CRATE_URL}/items/{item_id}", token=access)


def main() -> None:
    # 0. Liveness first — a clean failure message beats a confusing auth error.
    status, body = request("GET", f"{CRATE_URL}/health")
    if status != 200 or body.get("status") != "ok":
        fail(f"/health returned {status}: {body}")

    if not CLIENT_SECRET:
        fail("CRATE_SMOKE_CLIENT_SECRET is not set (add it to the deployed server/.env)")

    # 1. Mint a suite token for the allowlisted throwaway subject.
    status, body = request(
        "POST",
        SMOKE_TOKEN_URL,
        form={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "subject_email": SMOKE_EMAIL,
        },
    )
    if status != 200 or "access_token" not in body:
        fail(
            f"smoke token mint via {SMOKE_TOKEN_URL} returned {status}: {body}\n"
            f"  404 => SMOKE_CLIENTS unset on dragonfly-id (Compose needs --force-recreate\n"
            f"         after an .env edit; a plain `up` will not re-read it)\n"
            f"  401 => client id/secret does not match its SMOKE_CLIENTS entry\n"
            f"  403 => {SMOKE_EMAIL} is missing from SMOKE_SUBJECT_EMAILS, OR a CDN blocked the\n"
            f"         request before it reached the app (see _raw)\n"
            f"  _raw => a proxy/gateway answered, not the app. 'error code: 1010' is Cloudflare\n"
            f"         rejecting the client signature; reach dragonfly-id on the host instead\n"
            f"         (SMOKE_TOKEN_URL=http://host.docker.internal:8004/smoke/token)"
        )
    suite_token = body["access_token"]

    # 2. Trade it for a Crate session (find-or-create by email).
    status, body = request(
        "POST", f"{CRATE_URL}/auth/suite", body={"suite_token": suite_token}
    )
    if status != 200 or "access_token" not in body:
        fail(f"/auth/suite returned {status}: {body}")
    access = body["access_token"]

    # 3. Authenticated read proves the session + DB actually work.
    status, body = request("GET", f"{CRATE_URL}/users/me", token=access)
    if status != 200 or body.get("email", "").lower() != SMOKE_EMAIL.lower():
        fail(f"/users/me returned {status}: {body}")

    # 4. The scan pipeline — cleanup + identification, the thing Crate is for.
    if SCAN_ENABLED:
        run_scan_check(access)
    else:
        print("scan stage skipped (SMOKE_SCAN=0)")

    print("SMOKE_PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
