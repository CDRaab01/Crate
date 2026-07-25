"""eBay Sell (Inventory + Offer) posting — the approve→live-listing path.

Everything here runs ONLY from an explicit user tap (POST /items/{id}/post); the AI never
posts (CLAUDE.md §9). Always mocked in CI; the sandbox smoke goes live when a keyset and
the one-time consent exist.

Photo strategy: Crate is tailnet-only, so eBay can never fetch our photo URLs. Photos are
pushed as binaries via the Trading API's UploadSiteHostedPictures (eBay Picture Services)
using the same OAuth user token (IAF header) — the returned EPS URLs go into the
inventory item. This is the one legacy-XML call in the codebase; it's isolated here.
"""

import re

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.item import Item
from app.services import photo_store
from app.services.ebay import oauth

# Our condition enum → Inventory API condition enum.
_CONDITION_MAP = {
    "new": "NEW",
    "like_new": "LIKE_NEW",
    "good": "USED_GOOD",
    "fair": "USED_ACCEPTABLE",
    "poor": "FOR_PARTS_OR_NOT_WORKING",
}

_TRADING_HOSTS = {
    "production": "https://api.ebay.com/ws/api.dll",
    "sandbox": "https://api.sandbox.ebay.com/ws/api.dll",
}


def policies_configured() -> bool:
    return bool(
        settings.ebay_fulfillment_policy_id
        and settings.ebay_payment_policy_id
        and settings.ebay_return_policy_id
        and settings.ebay_location_postal_code
    )


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Content-Language": "en-US",
        "X-EBAY-C-MARKETPLACE-ID": settings.ebay_marketplace_id,
    }


async def _ensure_location(token: str, client: httpx.AsyncClient) -> None:
    """Create the ship-from inventory location once (publish requires one)."""
    key = settings.ebay_location_key
    r = await client.get(
        f"{oauth.api_host()}/sell/inventory/v1/location/{key}", headers=_headers(token)
    )
    if r.status_code == 200:
        return
    create = await client.post(
        f"{oauth.api_host()}/sell/inventory/v1/location/{key}",
        headers=_headers(token),
        json={
            "location": {
                "address": {
                    "postalCode": settings.ebay_location_postal_code,
                    "country": settings.ebay_location_country,
                }
            },
            "locationTypes": ["WAREHOUSE"],
            "merchantLocationStatus": "ENABLED",
            "name": "Crate ship-from",
        },
    )
    if create.status_code not in (200, 201, 204):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"eBay rejected the inventory location ({create.status_code})",
        )


async def upload_photos_to_eps(item: Item, token: str, client: httpx.AsyncClient) -> list[str]:
    """Push each photo binary to eBay Picture Services; returns EPS URLs (stored on the
    photo rows so a re-post never re-uploads)."""
    urls: list[str] = []
    for photo in item.photos:
        if photo.ebay_url:
            urls.append(photo.ebay_url)
            continue
        data = photo_store.read_bytes(photo.cleaned_path or photo.original_path)
        xml_request = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<UploadSiteHostedPicturesRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            "<PictureName>crate</PictureName>"
            "</UploadSiteHostedPicturesRequest>"
        )
        r = await client.post(
            _TRADING_HOSTS.get(settings.ebay_environment, _TRADING_HOSTS["sandbox"]),
            headers={
                "X-EBAY-API-COMPATIBILITY-LEVEL": "1193",
                "X-EBAY-API-CALL-NAME": "UploadSiteHostedPictures",
                "X-EBAY-API-SITEID": "0",
                "X-EBAY-API-IAF-TOKEN": token,
            },
            files={
                "XML Payload": (None, xml_request, "text/xml"),
                "image": ("photo.png", data, "application/octet-stream"),
            },
        )
        r.raise_for_status()
        match = re.search(r"<FullURL>([^<]+)</FullURL>", r.text)
        if match is None:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, "eBay Picture Services returned no URL"
            )
        photo.ebay_url = match.group(1).replace("&amp;", "&")
        urls.append(photo.ebay_url)
    return urls


def _require_ready(item: Item) -> None:
    missing = []
    if not item.title:
        missing.append("title")
    if item.chosen_price is None:
        missing.append("chosen price")
    if not item.condition:
        missing.append("condition")
    if not item.category_id:
        missing.append("eBay category")
    if not item.photos:
        missing.append("photos")
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Not ready to post — missing: {', '.join(missing)}",
        )


async def publish_item(
    db: AsyncSession, item: Item, client: httpx.AsyncClient | None = None
) -> str:
    """Draft → live fixed-price listing: EPS photos → inventory item → offer → publish.
    Returns the eBay listingId. Raises with honest statuses at every step."""
    if not oauth.configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "eBay keyset/RuName/Fernet key not configured",
        )
    if not policies_configured():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "eBay business policies not configured — set EBAY_FULFILLMENT/PAYMENT/RETURN"
            "_POLICY_ID and EBAY_LOCATION_POSTAL_CODE (one-time seller setup)",
        )
    _require_ready(item)

    token = await oauth.user_token(db, item.user_id, client=client)
    owns = client is None
    active = client or httpx.AsyncClient(timeout=30.0)
    try:
        await _ensure_location(token, active)
        image_urls = await upload_photos_to_eps(item, token, active)

        sku = str(item.id)
        aspects: dict[str, list[str]] = {}
        if item.brand:
            aspects["Brand"] = [item.brand]
        if item.model:
            aspects["Model"] = [item.model]

        inv = await active.put(
            f"{oauth.api_host()}/sell/inventory/v1/inventory_item/{sku}",
            headers=_headers(token),
            json={
                "product": {
                    "title": item.title,
                    "description": item.description or item.title,
                    "imageUrls": image_urls,
                    **({"aspects": aspects} if aspects else {}),
                },
                "condition": _CONDITION_MAP.get(item.condition, "USED_GOOD"),
                "availability": {"shipToLocationAvailability": {"quantity": 1}},
            },
        )
        if inv.status_code not in (200, 201, 204):
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"eBay rejected the inventory item ({inv.status_code}): {inv.text[:300]}",
            )

        offer_id = item.ebay_offer_id
        if offer_id is None:
            offer = await active.post(
                f"{oauth.api_host()}/sell/inventory/v1/offer",
                headers=_headers(token),
                json={
                    "sku": sku,
                    "marketplaceId": settings.ebay_marketplace_id,
                    "format": "FIXED_PRICE",
                    "availableQuantity": 1,
                    "categoryId": item.category_id,
                    "listingDescription": item.description or item.title,
                    "merchantLocationKey": settings.ebay_location_key,
                    "pricingSummary": {
                        "price": {"value": str(item.chosen_price), "currency": item.currency}
                    },
                    "listingPolicies": {
                        "fulfillmentPolicyId": settings.ebay_fulfillment_policy_id,
                        "paymentPolicyId": settings.ebay_payment_policy_id,
                        "returnPolicyId": settings.ebay_return_policy_id,
                    },
                },
            )
            if offer.status_code not in (200, 201):
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    f"eBay rejected the offer ({offer.status_code}): {offer.text[:300]}",
                )
            offer_id = offer.json()["offerId"]
            item.ebay_offer_id = offer_id

        pub = await active.post(
            f"{oauth.api_host()}/sell/inventory/v1/offer/{offer_id}/publish",
            headers=_headers(token),
        )
        if pub.status_code not in (200, 201):
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"eBay rejected the publish ({pub.status_code}): {pub.text[:300]}",
            )
        listing_id = pub.json().get("listingId")
        if not listing_id:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Publish returned no listingId")
        item.ebay_listing_id = str(listing_id)
        return item.ebay_listing_id
    finally:
        if owns:
            await active.aclose()


async def update_offer_price(
    db: AsyncSession, item: Item, client: httpx.AsyncClient | None = None
) -> None:
    """Push a changed price to the live offer (used by manual edits and the Phase 8 drop
    scheduler — the one documented unattended write path)."""
    if item.ebay_offer_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Item has no eBay offer")
    token = await oauth.user_token(db, item.user_id, client=client)
    owns = client is None
    active = client or httpx.AsyncClient(timeout=30.0)
    try:
        r = await active.get(
            f"{oauth.api_host()}/sell/inventory/v1/offer/{item.ebay_offer_id}",
            headers=_headers(token),
        )
        r.raise_for_status()
        offer = r.json()
        offer["pricingSummary"] = {
            "price": {"value": str(item.chosen_price), "currency": item.currency}
        }
        put = await active.put(
            f"{oauth.api_host()}/sell/inventory/v1/offer/{item.ebay_offer_id}",
            headers=_headers(token),
            json=offer,
        )
        if put.status_code not in (200, 204):
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"eBay rejected the price update ({put.status_code})",
            )
    finally:
        if owns:
            await active.aclose()


async def republish_offer(
    db: AsyncSession, item: Item, client: httpx.AsyncClient | None = None
) -> str:
    """Re-publish a withdrawn offer (relist after delist/return). The offer still exists
    on eBay; publish assigns a fresh listingId."""
    if item.ebay_offer_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Item has no eBay offer to relist")
    token = await oauth.user_token(db, item.user_id, client=client)
    owns = client is None
    active = client or httpx.AsyncClient(timeout=30.0)
    try:
        pub = await active.post(
            f"{oauth.api_host()}/sell/inventory/v1/offer/{item.ebay_offer_id}/publish",
            headers=_headers(token),
        )
        if pub.status_code not in (200, 201):
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"eBay rejected the relist ({pub.status_code}): {pub.text[:300]}",
            )
        listing_id = pub.json().get("listingId")
        if not listing_id:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Relist returned no listingId")
        item.ebay_listing_id = str(listing_id)
        return item.ebay_listing_id
    finally:
        if owns:
            await active.aclose()


async def end_listing(
    db: AsyncSession, item: Item, client: httpx.AsyncClient | None = None
) -> None:
    """Withdraw the offer (delist)."""
    if item.ebay_offer_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Item has no eBay offer")
    token = await oauth.user_token(db, item.user_id, client=client)
    owns = client is None
    active = client or httpx.AsyncClient(timeout=30.0)
    try:
        r = await active.post(
            f"{oauth.api_host()}/sell/inventory/v1/offer/{item.ebay_offer_id}/withdraw",
            headers=_headers(token),
        )
        if r.status_code not in (200, 204):
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, f"eBay rejected the withdraw ({r.status_code})"
            )
    finally:
        if owns:
            await active.aclose()
