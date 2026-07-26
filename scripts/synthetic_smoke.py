"""Post-deploy synthetic smoke for Crate (SSO-only, Magpie pattern).

Crate has no register/login endpoints, so the smoke mints an aud="suite" token from
dragonfly-id's POST /smoke/token using a confidential smoke credential, trades it at Crate's
POST /auth/suite, and exercises an authenticated read. Proves: the identity server trusts us,
Crate's JWKS validation + find-or-create works, and the DB is reachable — not just that
/health is up.

Config (env):
  CRATE_URL                 Crate base URL       (default http://127.0.0.1:8007)
  SMOKE_TOKEN_URL           dragonfly-id smoke endpoint
                            (default https://id.dragonflymedia.org/smoke/token)
  CRATE_SMOKE_CLIENT_ID     smoke client id      (default crate-smoke)
  CRATE_SMOKE_CLIENT_SECRET smoke client secret  (required — from the deployed .env)
  SMOKE_EMAIL               allowlisted subject  (default crate-smoke@dragonflymedia.org;
                            must be in dragonfly-id's SMOKE_SUBJECT_EMAILS)

Exit 0 + "SMOKE_PASS" on success; exit 1 with [FAIL] otherwise. Stdlib only.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

CRATE_URL = os.environ.get("CRATE_URL", "http://127.0.0.1:8007").rstrip("/")
SMOKE_TOKEN_URL = os.environ.get(
    "SMOKE_TOKEN_URL", "https://id.dragonflymedia.org/smoke/token"
)
CLIENT_ID = os.environ.get("CRATE_SMOKE_CLIENT_ID", "crate-smoke")
CLIENT_SECRET = os.environ.get("CRATE_SMOKE_CLIENT_SECRET", "")
SMOKE_EMAIL = os.environ.get("SMOKE_EMAIL", "crate-smoke@dragonflymedia.org")


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
    # A JSON scalar or array is valid JSON but not a mapping, and every caller does .get().
    return parsed if isinstance(parsed, dict) else {"_raw": str(parsed)[:200]}


def request(method: str, url: str, *, form=None, body=None, token=None, timeout=15):
    headers = {}
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
            f"  403 => {SMOKE_EMAIL} is missing from SMOKE_SUBJECT_EMAILS\n"
            f"  _raw => a proxy/gateway answered instead of the app, not an app error"
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

    print("SMOKE_PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
