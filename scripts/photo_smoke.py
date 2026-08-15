"""Send real photos through a running Crate and print what came back.

The unit tests prove the plumbing with synthetic images and a stubbed vision call. They
cannot prove the part that actually decides whether this is usable: whether Gemma, looking
at a photograph of YOUR shirt, reads the tag correctly and refuses to guess when it can't.
That needs real photos, a real LM Studio, and a human reading the output — which is what
this script is for.

Point it at a folder of clothing photos (one item per folder, or --each-file for one item
per photo), watch each draft process, and read the identification plus the archive gaps.
Nothing is posted anywhere: drafts are created, and `--keep` decides whether they stay.

Usage:
  # Against the deployed server, using your own photos (one item, several angles):
  python scripts/photo_smoke.py --dir ~/photos/navy-shirt

  # One item per file, for a batch of unrelated garments:
  python scripts/photo_smoke.py --dir ~/photos/wardrobe --each-file

  # No photos handy? Generate the synthetic samples and run those (plumbing check only —
  # a synthetic silhouette tells you nothing about tag reading):
  python scripts/photo_smoke.py --samples

Config (env, same as synthetic_smoke.py):
  CRATE_URL                 Crate base URL       (default http://127.0.0.1:8007)
  SMOKE_TOKEN_URL           dragonfly-id smoke endpoint
  CRATE_SMOKE_CLIENT_ID     smoke client id      (default crate-smoke)
  CRATE_SMOKE_CLIENT_SECRET smoke client secret  (required — from the deployed .env)
  SMOKE_EMAIL               allowlisted subject  (default crate-smoke@dragonflymedia.org)
  CRATE_ACCESS_TOKEN        skip the dragonfly-id round trip and use this Crate session
                            token directly (handy for local runs against a dev server)

Exit 0 when every photo produced a draft; exit 1 on the first hard failure. Stdlib only.
"""

import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

CRATE_URL = os.environ.get("CRATE_URL", "http://127.0.0.1:8007").rstrip("/")
SMOKE_TOKEN_URL = os.environ.get("SMOKE_TOKEN_URL", "https://id.dragonflymedia.org/smoke/token")
CLIENT_ID = os.environ.get("CRATE_SMOKE_CLIENT_ID", "crate-smoke")
CLIENT_SECRET = os.environ.get("CRATE_SMOKE_CLIENT_SECRET", "")
SMOKE_EMAIL = os.environ.get("SMOKE_EMAIL", "crate-smoke@dragonflymedia.org")
ACCESS_TOKEN = os.environ.get("CRATE_ACCESS_TOKEN", "")

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
MAX_PHOTOS_PER_ITEM = 8


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    sys.exit(1)


def decode_body(raw: bytes) -> dict:
    text = raw.decode(errors="replace").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except ValueError:
        return {"_raw": " ".join(text.split())[:200]}
    if isinstance(parsed, dict):
        return parsed
    # GET /items returns a JSON array. Stringifying it into "_raw" (repr, truncated at 200
    # chars) made list endpoints unreadable rather than merely awkward; hand it back intact.
    if isinstance(parsed, list):
        return {"_list": parsed}
    return {"_raw": str(parsed)[:200]}


def request(method: str, url: str, *, form=None, body=None, token=None, timeout=30):
    headers = {"User-Agent": "crate-photo-smoke/1.0"}
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


def post_photos(url: str, token: str, photos: list[Path], timeout: int):
    """multipart/form-data by hand — stdlib only, matching synthetic_smoke.py's constraint."""
    boundary = f"----crate{uuid.uuid4().hex}"
    body = bytearray()
    for path in photos:
        ctype = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        body += f"--{boundary}\r\n".encode()
        body += (
            f'Content-Disposition: form-data; name="photos"; filename="{path.name}"\r\n'
        ).encode()
        body += f"Content-Type: {ctype}\r\n\r\n".encode()
        body += path.read_bytes()
        body += b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers={
            "User-Agent": "crate-photo-smoke/1.0",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, decode_body(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, decode_body(e.read())
    except Exception as e:  # noqa: BLE001
        fail(f"POST {url}: {e}")


def authenticate() -> str:
    status, body = request("GET", f"{CRATE_URL}/health")
    if status != 200 or body.get("status") != "ok":
        fail(f"/health returned {status}: {body}")
    if ACCESS_TOKEN:
        # Pre-minted session: skips dragonfly-id entirely. Intended for a dev server where
        # the smoke credential isn't configured.
        return ACCESS_TOKEN
    if not CLIENT_SECRET:
        fail("CRATE_SMOKE_CLIENT_SECRET is not set (add it to the deployed server/.env)")

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
            "  (see scripts/synthetic_smoke.py for the 404/401/403 troubleshooting table)"
        )
    status, body = request("POST", f"{CRATE_URL}/auth/suite", body={"suite_token": body["access_token"]})
    if status != 200 or "access_token" not in body:
        fail(f"/auth/suite returned {status}: {body}")
    return body["access_token"]


def collect(directory: Path, each_file: bool) -> list[list[Path]]:
    """Group photos into items: one item per folder by default, or one per file."""
    photos = sorted(p for p in directory.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES)
    if not photos:
        fail(f"no images ({', '.join(sorted(IMAGE_SUFFIXES))}) found under {directory}")
    if each_file:
        return [[p] for p in photos]
    if len(photos) > MAX_PHOTOS_PER_ITEM:
        print(
            f"[warn] {len(photos)} photos in {directory} but an item takes at most "
            f"{MAX_PHOTOS_PER_ITEM}; using the first {MAX_PHOTOS_PER_ITEM}. "
            f"Use --each-file for one item per photo."
        )
    return [photos[:MAX_PHOTOS_PER_ITEM]]


def describe(item: dict) -> None:
    """Print the draft the way the review stack shows it, gaps included."""
    kind = item.get("item_kind", "general")
    print(f"    title      {item.get('title') or '(not identified)'}")
    print(f"    kind       {kind}")
    ident = " · ".join(
        str(v) for v in (item.get("brand"), item.get("model"), item.get("condition")) if v
    )
    if ident:
        print(f"    identity   {ident}")
    if kind == "clothing":
        garment = " · ".join(
            str(v)
            for v in (
                item.get("department"),
                item.get("size"),
                item.get("size_type"),
                item.get("color"),
                item.get("style"),
                item.get("fit"),
                item.get("sleeve_length"),
            )
            if v
        )
        print(f"    garment    {garment or '(nothing read from the tag)'}")
        print(f"    material   {item.get('material') or '(not read)'}")
    if item.get("weight_oz_est"):
        print(f"    ship est   {item['weight_oz_est']} oz  {item.get('dims_in_est')}")
    if item.get("quick_sale_price"):
        print(f"    prices     quick {item['quick_sale_price']} / patient {item['patient_price']}")
    gaps = item.get("missing_hand_only") or []
    if gaps:
        print(f"    NEEDS ITEM IN HAND: {', '.join(gaps)}")
    elif kind == "clothing":
        print("    archive complete — nothing left that needs the item in hand")
    # No "complete" claim for an unidentified draft: a general-kind item has no apparel gaps
    # by definition, so saying "complete" there would read as success when nothing was read.
    if item.get("scan_error"):
        print(f"    scan_error {item['scan_error']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--dir", type=Path, help="folder of real photos to send")
    source.add_argument(
        "--samples",
        action="store_true",
        help="use the generated synthetic samples (plumbing check only)",
    )
    parser.add_argument(
        "--each-file", action="store_true", help="treat every photo as its own item"
    )
    parser.add_argument(
        "--keep", action="store_true", help="leave the drafts behind instead of deleting them"
    )
    parser.add_argument(
        "--timeout", type=int, default=180, help="seconds to wait per draft (default 180)"
    )
    parser.add_argument(
        "--allow-scan-errors",
        action="store_true",
        help="treat a draft that failed identification as a pass (plumbing-only check)",
    )
    args = parser.parse_args()

    directory = args.dir
    if args.samples:
        # Import lazily: the generator lives with the tests and needs Pillow, which the
        # deployed container has but a bare checkout might not.
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
        from tests.fixtures.images import write_samples  # noqa: PLC0415

        directory = Path("sample_photos")
        write_samples(str(directory))
        print(f"Wrote synthetic samples to {directory.resolve()}")
        print("NOTE: synthetic silhouettes exercise the pipeline, not tag reading.\n")
        args.each_file = True

    groups = collect(directory, args.each_file)
    token = authenticate()
    print(f"Sending {len(groups)} item(s) from {directory} to {CRATE_URL}\n")

    failures = 0
    scan_errors: list[tuple[str, str]] = []
    for index, photos in enumerate(groups, start=1):
        names = ", ".join(p.name for p in photos)
        print(f"[{index}/{len(groups)}] {names}")
        status, body = post_photos(f"{CRATE_URL}/items/scan", token, photos, args.timeout)
        if status != 202 or "id" not in body:
            print(f"    [FAIL] /items/scan returned {status}: {body}")
            failures += 1
            continue

        item_id = body["id"]
        deadline = time.time() + args.timeout
        item = None
        while time.time() < deadline:
            status, item = request("GET", f"{CRATE_URL}/items/{item_id}", token=token)
            if status == 200 and item.get("processed_at"):
                break
            time.sleep(2)
        else:
            print(f"    [FAIL] draft {item_id} still processing after {args.timeout}s")
            failures += 1
            continue

        describe(item)
        # The point of this script is verifying identification actually works on real
        # photos. A draft that came back with a scan_error is a failure, not a pass —
        # reporting PHOTO_SMOKE_PASS with LM Studio unreachable would make the smoke a lie.
        if item.get("scan_error") and not args.allow_scan_errors:
            failures += 1
            scan_errors.append((names, item["scan_error"]))
        if not args.keep:
            request("DELETE", f"{CRATE_URL}/items/{item_id}", token=token)
        else:
            print(f"    kept as {item_id}")
        print()

    if failures:
        print(f"[FAIL] {failures} of {len(groups)} item(s) failed")
        for names, err in scan_errors:
            print(f"  {names}: {err}")
        # Print the remediation that actually matches what went wrong. The hint below used
        # to be printed unconditionally, so a 'low_confidence' draft — the ordinary, correct
        # outcome for a photo of a whole clothing rack — read as "LM Studio is unreachable"
        # and sent you debugging container networking that was working fine.
        if any(e.startswith("identify_unavailable") for _, e in scan_errors):
            print(
                "\n  'identify_unavailable' => the server could not reach LM Studio.\n"
                "  Inside the container localhost is the container: LM_STUDIO_BASE_URL should be\n"
                "  http://host.docker.internal:1234/v1. Check GET :1234/v1/models for the model\n"
                "  that is actually loaded (LM_STUDIO_VISION_MODEL must match)."
            )
        if any(e == "low_confidence" for _, e in scan_errors):
            print(
                "\n  'low_confidence' => LM Studio answered, but could not identify one item\n"
                "  in those photos. Usually the photo shows several items (a rack, a pile) or\n"
                "  the item is unclear — reshoot one item against a plain background. Pass\n"
                "  --allow-scan-errors to treat this as a pass."
            )
        sys.exit(1)
    print(f"PHOTO_SMOKE_PASS ({len(groups)} item(s))")
    sys.exit(0)


if __name__ == "__main__":
    main()
