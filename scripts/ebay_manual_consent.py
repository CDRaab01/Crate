"""Complete the one-time eBay seller consent by hand, without the redirect working.

Why this exists. eBay's consent flow ends with a browser redirect to the RuName's accepted
URL carrying `?code=...`. In the 2026-08-15 audit that redirect arrived six times with NO
query string at all, and everything on Crate's side was proven good — so this script removes
the dependency on eBay building that redirect correctly. It relies instead on a property of
eBay's own portal: with the RuName's accepted URL left BLANK, eBay lands on its own hosted
success page after consent, and that page's URL contains the authorization code.

For a single-user app whose consent happens once per ~18 months, paste-the-code is a
perfectly good permanent flow, not a workaround.

Usage. The image does not ship scripts/ (build context is server/), so copy it in first —
the same pattern the deploy smoke uses:

  docker compose cp scripts/ebay_manual_consent.py server:/tmp/consent.py

  1. Print the consent URL:
       docker compose exec server python /tmp/consent.py --url
     Open it in any browser, sign in with the SANDBOX test user, accept.

  2. eBay lands on its own success page. Copy the WHOLE address-bar URL (it contains
     `code=v%5E1.1%23...`), or just the code value, and within ~5 minutes run:
       docker compose exec server python /tmp/consent.py --code '<paste>'
     Quote it — real codes contain ^, #, & and percent-escapes. The script accepts either
     the full URL or the bare code, encoded or already-decoded, and sorts it out.

The code is passed as an ARGUMENT, not read from stdin: `docker compose exec -T` and
`!`-prefixed shells have no interactive stdin, a lesson this project has already paid for.

The token exchange calls oauth.exchange_code() directly — `state` exists to bind the
browser redirect to a session, and there is no redirect here. Tokens land Fernet-encrypted
in ebay_credentials exactly as the callback would have stored them.
"""

import argparse
import asyncio
import sys
import urllib.parse

sys.path.insert(0, "/app")

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.user import User
from app.services.ebay import oauth

DEFAULT_EMAIL = "cdraab01@gmail.com"


def extract_code(raw: str) -> str:
    """The authorization code, from either a pasted URL or a bare (possibly encoded) code.

    eBay codes are 'v^1.1#i^1#...'-shaped and arrive percent-encoded in URLs. exchange_code
    needs the DECODED form — the token endpoint re-encodes it itself; double-encoding is a
    silent invalid_grant.
    """
    raw = raw.strip()
    if "://" in raw or raw.startswith("/"):
        query = urllib.parse.urlparse(raw).query
        params = urllib.parse.parse_qs(query)  # parse_qs already decodes
        codes = params.get("code")
        if not codes:
            raise SystemExit(f"no code= parameter in that URL (params: {sorted(params)})")
        return codes[0]
    # Bare code: decode only if it still looks encoded, so an already-decoded paste
    # (containing a literal '#') is not mangled by a second unquote.
    return urllib.parse.unquote(raw) if "%" in raw and "#" not in raw else raw


async def resolve_user_id(email: str):
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            raise SystemExit(f"no user with email {email!r} — check --email")
        return user.id


async def run(args: argparse.Namespace) -> None:
    if not oauth.configured():
        raise SystemExit(
            "eBay is not configured (client id/secret, RuName, Fernet key) — fix .env first"
        )
    user_id = await resolve_user_id(args.email)

    if args.url:
        print("Open this in a browser, sign in with the SANDBOX user, accept:\n")
        print(oauth.authorize_url(str(user_id)))
        print("\nThen re-run with --code '<the code or the whole success-page URL>'")
        return

    code = extract_code(args.code)
    async with AsyncSessionLocal() as db:
        creds = await oauth.exchange_code(db, user_id, code)
        print("eBay connected.")
        print(f"  environment       : {creds.environment}")
        print(f"  access expires    : {creds.expires_at}")
        print(f"  refresh expires   : {creds.refresh_expires_at}  (reconsent needed after)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url", action="store_true", help="print the consent URL and exit")
    group.add_argument("--code", help="authorization code, or the full success-page URL")
    parser.add_argument("--email", default=DEFAULT_EMAIL, help=f"user (default {DEFAULT_EMAIL})")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
