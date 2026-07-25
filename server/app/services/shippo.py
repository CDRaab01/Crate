"""Shippo client: rate shopping + label purchase (USPS/UPS/FedEx).

Chosen over eBay's own Logistics API because that one is restricted-access (locked
decision, CLAUDE.md §0). Test mode in dev via the test key; ALWAYS mocked in CI.
Unconfigured ⇒ 503 with a clear message (the Spoonacular precedent). Label purchase
costs real money — it only ever runs from the explicit buy-label tap.
"""

from dataclasses import dataclass
from decimal import Decimal

import httpx
from fastapi import HTTPException, status

from app.config import settings


def configured() -> bool:
    return bool(
        settings.shippo_api_key
        and settings.ship_from_name
        and settings.ship_from_street1
        and settings.ship_from_city
        and settings.ship_from_state
        and settings.ship_from_zip
    )


def require_configured() -> None:
    if not configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Shippo/ship-from address not configured — set SHIPPO_API_KEY and the "
            "SHIP_FROM_* values in server/.env",
        )


@dataclass(frozen=True)
class Rate:
    rate_id: str
    provider: str
    service: str
    amount: Decimal
    currency: str
    estimated_days: int | None


@dataclass(frozen=True)
class Label:
    """What the transaction itself proves: tracking + the PDF. Carrier/service/cost come
    from the QUOTED rate the user picked (the transaction echoes the rate only as an id)."""

    tracking_number: str
    label_url: str


def _headers() -> dict:
    return {"Authorization": f"ShippoToken {settings.shippo_api_key}"}


def _address_from() -> dict:
    return {
        "name": settings.ship_from_name,
        "street1": settings.ship_from_street1,
        "city": settings.ship_from_city,
        "state": settings.ship_from_state,
        "zip": settings.ship_from_zip,
        "country": settings.ship_from_country,
    }


def _address_to(buyer_address: dict) -> dict:
    contact = buyer_address.get("address") or {}
    return {
        "name": buyer_address.get("name") or "Buyer",
        "street1": contact.get("addressLine1") or "",
        "street2": contact.get("addressLine2") or "",
        "city": contact.get("city") or "",
        "state": contact.get("stateOrProvince") or "",
        "zip": contact.get("postalCode") or "",
        "country": contact.get("countryCode") or "US",
        "phone": buyer_address.get("phone") or "",
    }


async def get_rates(
    buyer_address: dict,
    weight_oz: Decimal,
    dims_in: dict | None,
    client: httpx.AsyncClient | None = None,
) -> list[Rate]:
    """Create a synchronous shipment and return its carrier rates (unsorted — the
    endpoint sorts per the user's cheapest/fastest preference)."""
    require_configured()
    parcel = {
        "length": str((dims_in or {}).get("l", 10)),
        "width": str((dims_in or {}).get("w", 8)),
        "height": str((dims_in or {}).get("h", 4)),
        "distance_unit": "in",
        "weight": str(weight_oz),
        "mass_unit": "oz",
    }
    owns = client is None
    active = client or httpx.AsyncClient(timeout=30.0)
    try:
        resp = await active.post(
            f"{settings.shippo_base_url}/shipments/",
            headers=_headers(),
            json={
                "address_from": _address_from(),
                "address_to": _address_to(buyer_address),
                "parcels": [parcel],
                "async": False,
            },
        )
        resp.raise_for_status()
        body = resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Shippo rate quote failed") from e
    finally:
        if owns:
            await active.aclose()

    rates: list[Rate] = []
    for raw in body.get("rates", []):
        try:
            amount = Decimal(str(raw["amount"]))
        except Exception:
            continue
        rates.append(
            Rate(
                rate_id=str(raw.get("object_id")),
                provider=str(raw.get("provider") or "?"),
                service=str((raw.get("servicelevel") or {}).get("name") or "?"),
                amount=amount,
                currency=str(raw.get("currency") or "USD"),
                estimated_days=raw.get("estimated_days"),
            )
        )
    return rates


async def buy_label(rate_id: str, client: httpx.AsyncClient | None = None) -> Label:
    """Purchase the label for a quoted rate. REAL MONEY — explicit user tap only."""
    require_configured()
    owns = client is None
    active = client or httpx.AsyncClient(timeout=60.0)
    try:
        resp = await active.post(
            f"{settings.shippo_base_url}/transactions/",
            headers=_headers(),
            json={"rate": rate_id, "label_file_type": "PDF", "async": False},
        )
        resp.raise_for_status()
        body = resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Shippo label purchase failed") from e
    finally:
        if owns:
            await active.aclose()

    if body.get("status") != "SUCCESS":
        messages = (
            "; ".join(str(m.get("text", "")) for m in (body.get("messages") or []))
            or "no reason given"
        )
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Shippo rejected the label: {messages}")
    tracking = body.get("tracking_number")
    label_url = body.get("label_url")
    if not tracking or not label_url:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Shippo transaction succeeded without tracking/label"
        )
    return Label(tracking_number=str(tracking), label_url=str(label_url))
