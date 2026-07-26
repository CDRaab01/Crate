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
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")
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
        fail(f"smoke token mint returned {status}: {body}")
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
