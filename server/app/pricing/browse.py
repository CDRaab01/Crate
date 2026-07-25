"""eBay Browse API client — active-comp search with an application token.

Application (client-credentials) token only: Browse needs no user consent, so pricing
works the moment a keyset exists — independent of the Phase 5 seller OAuth. Sandbox vs
production comes from `ebay_environment`. Always mocked in CI; unconfigured ⇒ the caller
skips pricing (pipeline) or 503s (/comps endpoint).
"""

import base64
import time
from decimal import Decimal, InvalidOperation

import httpx

from app.config import settings
from app.pricing.comps import Comp

_HOSTS = {
    "production": "https://api.ebay.com",
    "sandbox": "https://api.sandbox.ebay.com",
}

# Our condition enum → eBay conditionIds (Browse `filter=conditionIds:{...}`).
# new/like_new shop against new-ish listings; the used tiers shop against used.
_CONDITION_IDS = {
    "new": "1000",
    "like_new": "1000|1500|2750",  # new, open box, like new
    "good": "3000|4000",  # used, very good
    "fair": "3000|4000|5000",
    "poor": "5000|6000",  # acceptable, for parts
}

_TOKEN_CACHE: dict = {"token": None, "expires_at": 0.0}


def configured() -> bool:
    return bool(settings.ebay_client_id and settings.ebay_client_secret)


def _host() -> str:
    return _HOSTS.get(settings.ebay_environment, _HOSTS["sandbox"])


async def _app_token(client: httpx.AsyncClient) -> str:
    now = time.time()
    if _TOKEN_CACHE["token"] and now < _TOKEN_CACHE["expires_at"] - 60:
        return _TOKEN_CACHE["token"]

    basic = base64.b64encode(
        f"{settings.ebay_client_id}:{settings.ebay_client_secret}".encode()
    ).decode()
    resp = await client.post(
        f"{_host()}/identity/v1/oauth2/token",
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        },
    )
    resp.raise_for_status()
    body = resp.json()
    _TOKEN_CACHE.update(
        token=body["access_token"], expires_at=now + float(body.get("expires_in", 7200))
    )
    return _TOKEN_CACHE["token"]


async def search_active_comps(
    query: str,
    condition: str | None,
    limit: int = 50,
    client: httpx.AsyncClient | None = None,
) -> list[Comp]:
    """Fixed-price active listings for `query`, condition-bucketed. Raises httpx errors —
    callers decide whether that degrades (pipeline) or surfaces (endpoint)."""
    owns_client = client is None
    active = client or httpx.AsyncClient(timeout=settings.external_timeout_seconds)
    try:
        token = await _app_token(active)
        filters = ["buyingOptions:{FIXED_PRICE}"]
        condition_ids = _CONDITION_IDS.get(condition or "")
        if condition_ids:
            filters.append(f"conditionIds:{{{condition_ids}}}")
        resp = await active.get(
            f"{_host()}/buy/browse/v1/item_summary/search",
            params={"q": query, "limit": str(limit), "filter": ",".join(filters)},
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": settings.ebay_marketplace_id,
            },
        )
        resp.raise_for_status()
        body = resp.json()
    finally:
        if owns_client:
            await active.aclose()

    comps: list[Comp] = []
    for summary in body.get("itemSummaries", []):
        price_field = summary.get("price") or {}
        try:
            price = Decimal(str(price_field.get("value")))
        except (InvalidOperation, TypeError):
            continue
        comps.append(
            Comp(
                title=str(summary.get("title") or ""),
                price=price,
                condition=summary.get("condition"),
                url=summary.get("itemWebUrl"),
            )
        )
    return comps


def reset_token_cache() -> None:
    """Test seam."""
    _TOKEN_CACHE.update(token=None, expires_at=0.0)
