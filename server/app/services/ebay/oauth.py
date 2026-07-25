"""eBay seller OAuth (authorization-code flow) + the encrypted token store.

The consent happens ONCE, from a browser on the tailnet: the app asks GET /ebay/connect
for the authorize URL, the browser lands on eBay, eBay redirects to /ebay/callback (the
RuName points at the ts.net URL), and the code is exchanged server-side. Tokens persist
in `ebay_credentials` encrypted with Fernet — never plaintext at rest (CLAUDE.md §9).

State handling is an in-process dict (10-minute TTL): Crate is a single-user,
single-process app; a restart mid-consent just means clicking Connect again.
"""

import base64
import datetime
import secrets
import time

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.ebay_credentials import EbayCredentials

_AUTH_HOSTS = {
    "production": "https://auth.ebay.com",
    "sandbox": "https://auth.sandbox.ebay.com",
}
_API_HOSTS = {
    "production": "https://api.ebay.com",
    "sandbox": "https://api.sandbox.ebay.com",
}

# Seller scopes: inventory (create/publish listings) + fulfillment (orders, tracking).
USER_SCOPES = " ".join(
    [
        "https://api.ebay.com/oauth/api_scope/sell.inventory",
        "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
    ]
)

# state -> (user_id str, issued_at). Single-user app: in-process is deliberate.
_PENDING_STATES: dict[str, tuple[str, float]] = {}
_STATE_TTL_SECONDS = 600


def api_host() -> str:
    return _API_HOSTS.get(settings.ebay_environment, _API_HOSTS["sandbox"])


def _auth_host() -> str:
    return _AUTH_HOSTS.get(settings.ebay_environment, _AUTH_HOSTS["sandbox"])


def configured() -> bool:
    return bool(
        settings.ebay_client_id
        and settings.ebay_client_secret
        and settings.ebay_ru_name
        and settings.fernet_key
    )


def _fernet() -> Fernet:
    return Fernet(settings.fernet_key.encode())


def encrypt(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def decrypt(token_enc: str) -> str:
    try:
        return _fernet().decrypt(token_enc.encode()).decode()
    except InvalidToken:
        # Key rotated/lost: the stored grant is unusable — reconnect is the only fix.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Stored eBay tokens can't be decrypted (FERNET_KEY changed?) — reconnect eBay.",
        )


def authorize_url(user_id: str) -> str:
    state = secrets.token_urlsafe(24)
    now = time.time()
    # Sweep expired states so the dict can't grow unbounded.
    for key in [k for k, (_, t) in _PENDING_STATES.items() if now - t > _STATE_TTL_SECONDS]:
        _PENDING_STATES.pop(key, None)
    _PENDING_STATES[state] = (user_id, now)
    query = httpx.QueryParams(
        {
            "client_id": settings.ebay_client_id,
            "response_type": "code",
            "redirect_uri": settings.ebay_ru_name,
            "scope": USER_SCOPES,
            "state": state,
        }
    )
    return f"{_auth_host()}/oauth2/authorize?{query}"


def consume_state(state: str) -> str | None:
    entry = _PENDING_STATES.pop(state, None)
    if entry is None:
        return None
    user_id, issued_at = entry
    if time.time() - issued_at > _STATE_TTL_SECONDS:
        return None
    return user_id


def _basic_auth() -> str:
    raw = f"{settings.ebay_client_id}:{settings.ebay_client_secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


async def _token_request(data: dict, client: httpx.AsyncClient | None = None) -> dict:
    owns = client is None
    active = client or httpx.AsyncClient(timeout=settings.external_timeout_seconds)
    try:
        resp = await active.post(
            f"{api_host()}/identity/v1/oauth2/token",
            headers={
                "Authorization": _basic_auth(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=data,
        )
        resp.raise_for_status()
        return resp.json()
    finally:
        if owns:
            await active.aclose()


async def exchange_code(
    db: AsyncSession, user_id, code: str, client: httpx.AsyncClient | None = None
) -> EbayCredentials:
    body = await _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.ebay_ru_name,
        },
        client=client,
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    expires_at = now + datetime.timedelta(seconds=int(body.get("expires_in", 7200)))
    refresh_expires_at = now + datetime.timedelta(
        seconds=int(body.get("refresh_token_expires_in", 47304000))  # ~18 months
    )

    creds = (
        await db.execute(select(EbayCredentials).where(EbayCredentials.user_id == user_id))
    ).scalar_one_or_none()
    if creds is None:
        creds = EbayCredentials(
            user_id=user_id,
            access_token_enc=encrypt(body["access_token"]),
            refresh_token_enc=encrypt(body["refresh_token"]),
            expires_at=expires_at,
            refresh_expires_at=refresh_expires_at,
            environment=settings.ebay_environment,
            scopes=USER_SCOPES,
        )
        db.add(creds)
    else:
        creds.access_token_enc = encrypt(body["access_token"])
        creds.refresh_token_enc = encrypt(body["refresh_token"])
        creds.expires_at = expires_at
        creds.refresh_expires_at = refresh_expires_at
        creds.environment = settings.ebay_environment
        creds.scopes = USER_SCOPES
    await db.commit()
    return creds


async def user_token(db: AsyncSession, user_id, client: httpx.AsyncClient | None = None) -> str:
    """A live access token for the user — refreshed (and re-persisted) when it's within
    5 minutes of expiry. 409 when eBay was never connected."""
    creds = (
        await db.execute(select(EbayCredentials).where(EbayCredentials.user_id == user_id))
    ).scalar_one_or_none()
    if creds is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "eBay is not connected — run the one-time consent first"
        )

    now = datetime.datetime.now(datetime.timezone.utc)
    if creds.expires_at > now + datetime.timedelta(minutes=5):
        return decrypt(creds.access_token_enc)

    if creds.refresh_expires_at <= now:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "eBay refresh token expired (~18-month lifetime) — reconnect eBay.",
        )

    body = await _token_request(
        {
            "grant_type": "refresh_token",
            "refresh_token": decrypt(creds.refresh_token_enc),
            "scope": USER_SCOPES,
        },
        client=client,
    )
    creds.access_token_enc = encrypt(body["access_token"])
    creds.expires_at = now + datetime.timedelta(seconds=int(body.get("expires_in", 7200)))
    await db.commit()
    return body["access_token"]
