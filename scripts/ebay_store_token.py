"""Store an eBay user token that was issued OUTSIDE the authorization-code flow.

Why this exists. Crate's `/ebay/callback` never receives a code: across eleven attempts on
2026-08-15/16 eBay rendered consent, the owner pressed "Agree and Continue", and the
redirect arrived with no query string and no fragment (the fragment probe in
`routers/ebay.py` proves the latter). eBay's redirect builder is broken for this RuName, so
the code half of the flow is unreachable.

eBay's own developer portal has a token generator for exactly Crate's case — an app serving
one eBay account, its owner's: **Get a User Token Here → OAuth (new security) → Sign in to
Sandbox**. It signs in, takes consent, and prints the token straight onto the page. No
redirect anywhere in it. This script takes what that page prints and stores it the way
`exchange_code` would have.

Usage (the image does not ship scripts/ — build context is server/ — so copy it in first):

    docker compose cp scripts/ebay_store_token.py server:/tmp/store.py
    docker compose exec server python /tmp/store.py --access-token '<token>' \
        --refresh-token '<token>' --refresh-expires-in 47304000

`--refresh-token` is optional because the portal does not always surface one. Without it the
grant dies when the access token does (2 hours) and the portal trip must be repeated — fine
for proving a first posting works, not fine as a permanent arrangement, so the script says
so loudly rather than leaving a surprise for later.

Tokens are arguments, not stdin: `docker compose exec -T` has no interactive stdin, a lesson
this project has already paid for twice.
"""

import argparse
import asyncio
import datetime
import sys

sys.path.insert(0, "/app")

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.ebay_credentials import EbayCredentials
from app.models.user import User
from app.services.ebay import oauth

DEFAULT_EMAIL = "cdraab01@gmail.com"
# eBay user access tokens are 2h; the portal prints the token but not always its lifetime.
DEFAULT_EXPIRES_IN = 7200


async def run(args: argparse.Namespace) -> None:
    if not settings.fernet_key:
        raise SystemExit("FERNET_KEY is unset — tokens are never stored in plaintext")

    now = datetime.datetime.now(datetime.UTC)
    expires_at = now + datetime.timedelta(seconds=args.expires_in)

    if args.refresh_token:
        refresh_expires_at = now + datetime.timedelta(seconds=args.refresh_expires_in)
    else:
        # No refresh token: the grant is only as good as the access token. Recording the
        # same instant (rather than a fake 18 months) keeps /ebay/status honest and makes
        # user_token() raise its "reconnect" 409 at the right moment instead of trying a
        # refresh that cannot work.
        refresh_expires_at = expires_at

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == args.email))).scalar_one_or_none()
        if user is None:
            raise SystemExit(f"no user with email {args.email!r} — check --email")

        creds = (
            await db.execute(select(EbayCredentials).where(EbayCredentials.user_id == user.id))
        ).scalar_one_or_none()
        if creds is None:
            creds = EbayCredentials(user_id=user.id)
            db.add(creds)

        creds.access_token_enc = oauth.encrypt(args.access_token)
        # The column is NOT NULL; store the access token as its own "refresh" when none was
        # issued. user_token() never reaches it — refresh_expires_at has already passed by
        # the time a refresh would be attempted.
        creds.refresh_token_enc = oauth.encrypt(args.refresh_token or args.access_token)
        creds.expires_at = expires_at
        creds.refresh_expires_at = refresh_expires_at
        creds.environment = settings.ebay_environment
        creds.scopes = oauth.USER_SCOPES
        await db.commit()

    print("eBay credentials stored (encrypted).")
    print(f"  environment     : {settings.ebay_environment}")
    print(f"  access expires  : {expires_at.isoformat()}")
    if args.refresh_token:
        print(f"  refresh expires : {refresh_expires_at.isoformat()}")
    else:
        print("  refresh token   : NONE — this grant dies with the access token above.")
        print("  Re-run the portal token generator to renew; there is no auto-refresh.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--access-token", required=True, help="user access token")
    parser.add_argument("--refresh-token", help="refresh token, if the portal showed one")
    parser.add_argument("--expires-in", type=int, default=DEFAULT_EXPIRES_IN)
    parser.add_argument("--refresh-expires-in", type=int, default=47304000)  # ~18 months
    parser.add_argument("--email", default=DEFAULT_EMAIL, help=f"user (default {DEFAULT_EMAIL})")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
