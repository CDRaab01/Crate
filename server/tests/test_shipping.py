"""Sale → ship flow: confirm step gates rates, preference sorting, label purchase with
tracking push + lifecycle. Shippo + eBay fully mocked (CLAUDE.md §8)."""

import datetime
import json
from decimal import Decimal

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.ebay_credentials import EbayCredentials
from app.models.item import Item
from app.models.sale import Sale
from app.models.user_settings import UserSettings
from app.services import shippo
from app.services.ebay import fulfillment, oauth

FERNET_KEY = Fernet.generate_key().decode()

BUYER_ADDRESS = {
    "name": "Pat Buyer",
    "address": {
        "addressLine1": "1 Fish Rd",
        "city": "Lansing",
        "stateOrProvince": "MI",
        "postalCode": "48864",
        "countryCode": "US",
    },
    "phone": "5551234567",
}

RATES_BODY = {
    "rates": [
        {
            "object_id": "rate-usps",
            "provider": "USPS",
            "servicelevel": {"name": "Priority Mail"},
            "amount": "8.10",
            "currency": "USD",
            "estimated_days": 2,
        },
        {
            "object_id": "rate-ups",
            "provider": "UPS",
            "servicelevel": {"name": "Ground"},
            "amount": "9.50",
            "currency": "USD",
            "estimated_days": 4,
        },
        {
            "object_id": "rate-fedex",
            "provider": "FedEx",
            "servicelevel": {"name": "Overnight"},
            "amount": "24.00",
            "currency": "USD",
            "estimated_days": 1,
        },
    ]
}


@pytest.fixture(autouse=True)
def shipping_ready(monkeypatch):
    monkeypatch.setattr(settings, "shippo_api_key", "shippo_test_key")
    monkeypatch.setattr(settings, "ship_from_name", "C. Seller")
    monkeypatch.setattr(settings, "ship_from_street1", "2 Crate Ln")
    monkeypatch.setattr(settings, "ship_from_city", "Okemos")
    monkeypatch.setattr(settings, "ship_from_state", "MI")
    monkeypatch.setattr(settings, "ship_from_zip", "48864")
    monkeypatch.setattr(settings, "ebay_client_id", "test-id")
    monkeypatch.setattr(settings, "ebay_client_secret", "test-secret")
    monkeypatch.setattr(settings, "ebay_ru_name", "Test-RuName")
    monkeypatch.setattr(settings, "fernet_key", FERNET_KEY)
    monkeypatch.setattr(settings, "ebay_environment", "sandbox")


async def _seed_sold(user_id, *, confirmed=False) -> Item:
    async with AsyncSessionLocal() as db:
        item = Item(
            user_id=user_id,
            title="Rapala F11",
            status="sold",
            weight_oz_est=Decimal("3.50"),
            dims_in_est={"l": 6, "w": 3, "h": 2},
            weight_confirmed=confirmed,
            chosen_price=Decimal("15.00"),
        )
        db.add(item)
        await db.flush()
        db.add(
            Sale(
                item_id=item.id,
                ebay_order_id=f"ORDER-{item.id.hex[:8]}",
                sale_price=Decimal("15.00"),
                sale_date=datetime.datetime.now(datetime.timezone.utc),
                buyer_username="fish4life",
                buyer_address=BUYER_ADDRESS,
            )
        )
        now = datetime.datetime.now(datetime.timezone.utc)
        db.add(
            EbayCredentials(
                user_id=user_id,
                access_token_enc=oauth.encrypt("live-token"),
                refresh_token_enc=oauth.encrypt("refresh"),
                expires_at=now + datetime.timedelta(hours=1),
                refresh_expires_at=now + datetime.timedelta(days=400),
                environment="sandbox",
            )
        )
        await db.commit()
        await db.refresh(item)
        return item


async def test_confirm_weight_gates_rates(auth_client, monkeypatch):
    item = await _seed_sold(auth_client.user_id, confirmed=False)

    r = await auth_client.get(f"/items/{item.id}/rates")
    assert r.status_code == 409
    assert "confirm" in r.json()["detail"].lower()

    r = await auth_client.post(
        f"/items/{item.id}/confirm-weight",
        json={"weight_oz": "4.5", "dims_in": {"l": 7, "w": 4, "h": 3}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["weight_confirmed"] is True
    assert body["weight_oz_est"] == "4.50"


async def test_rates_sorted_by_preference(auth_client, monkeypatch):
    item = await _seed_sold(auth_client.user_id, confirmed=True)

    rec: dict = {}

    async def fake_get_rates(buyer_address, weight_oz, dims_in, client=None):
        rec["weight"] = weight_oz
        return [
            shippo.Rate("rate-usps", "USPS", "Priority Mail", Decimal("8.10"), "USD", 2),
            shippo.Rate("rate-ups", "UPS", "Ground", Decimal("9.50"), "USD", 4),
            shippo.Rate("rate-fedex", "FedEx", "Overnight", Decimal("24.00"), "USD", 1),
        ]

    import app.routers.shipping as shipping_router

    monkeypatch.setattr(shipping_router.shippo, "get_rates", fake_get_rates)

    # Default preference: cheapest first.
    r = await auth_client.get(f"/items/{item.id}/rates")
    assert r.status_code == 200, r.text
    assert [x["provider"] for x in r.json()] == ["USPS", "UPS", "FedEx"]
    assert rec["weight"] == Decimal("3.50")

    # Flip to fastest.
    async with AsyncSessionLocal() as db:
        prefs = (
            await db.execute(
                select(UserSettings).where(UserSettings.user_id == auth_client.user_id)
            )
        ).scalar_one_or_none()
        if prefs is None:
            db.add(UserSettings(user_id=auth_client.user_id, shipping_preference="fastest"))
        else:
            prefs.shipping_preference = "fastest"
        await db.commit()

    r = await auth_client.get(f"/items/{item.id}/rates")
    assert [x["provider"] for x in r.json()] == ["FedEx", "USPS", "UPS"]


async def test_rates_503_when_shippo_unconfigured(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "shippo_api_key", None)
    item = await _seed_sold(auth_client.user_id, confirmed=True)
    r = await auth_client.get(f"/items/{item.id}/rates")
    assert r.status_code == 503


async def test_shippo_rate_parsing():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["address_to"]["city"] == "Lansing"
        assert body["parcels"][0]["weight"] == "3.50"
        return httpx.Response(200, json=RATES_BODY)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        rates = await shippo.get_rates(
            BUYER_ADDRESS, Decimal("3.50"), {"l": 6, "w": 3, "h": 2}, client=http
        )
    assert [r.provider for r in rates] == ["USPS", "UPS", "FedEx"]
    assert rates[0].amount == Decimal("8.10")


async def test_buy_label_happy_path(auth_client, monkeypatch):
    item = await _seed_sold(auth_client.user_id, confirmed=True)

    async def fake_buy(rate_id, client=None):
        assert rate_id == "rate-usps"
        return shippo.Label(
            tracking_number="9400111899560000000000", label_url="https://shippo/label.pdf"
        )

    pushed: dict = {}

    async def fake_push_tracking(db, user_id, order_id, tracking, carrier, client=None):
        pushed.update(order_id=order_id, tracking=tracking, carrier=carrier)

    import app.routers.shipping as shipping_router

    monkeypatch.setattr(shipping_router.shippo, "buy_label", fake_buy)
    monkeypatch.setattr(shipping_router.fulfillment, "push_tracking", fake_push_tracking)

    r = await auth_client.post(
        f"/items/{item.id}/buy-label",
        json={
            "rate_id": "rate-usps",
            "provider": "USPS",
            "service": "Priority Mail",
            "amount": "8.10",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ship_status"] == "shipped"
    assert body["tracking_number"] == "9400111899560000000000"
    assert body["label_url"] == "https://shippo/label.pdf"
    assert body["carrier"] == "USPS"
    assert body["label_cost"] == "8.10"
    assert pushed["tracking"] == "9400111899560000000000"

    async with AsyncSessionLocal() as db:
        stored = (await db.execute(select(Item).where(Item.id == item.id))).scalar_one()
        assert stored.status == "shipped"

    # A second tap can't double-buy.
    r = await auth_client.post(
        f"/items/{item.id}/buy-label",
        json={
            "rate_id": "rate-usps",
            "provider": "USPS",
            "service": "Priority Mail",
            "amount": "8.10",
        },
    )
    assert r.status_code == 409


async def test_buy_label_survives_tracking_push_failure(auth_client, monkeypatch):
    item = await _seed_sold(auth_client.user_id, confirmed=True)

    async def fake_buy(rate_id, client=None):
        return shippo.Label(tracking_number="TRACK-1", label_url="https://shippo/l.pdf")

    async def dead_push(*args, **kwargs):
        raise RuntimeError("eBay down")

    import app.routers.shipping as shipping_router

    monkeypatch.setattr(shipping_router.shippo, "buy_label", fake_buy)
    monkeypatch.setattr(shipping_router.fulfillment, "push_tracking", dead_push)

    r = await auth_client.post(
        f"/items/{item.id}/buy-label",
        json={"rate_id": "r", "provider": "USPS", "service": "Ground Advantage", "amount": "5.00"},
    )
    # The label is real either way — state advances, the ntfy note carries the warning.
    assert r.status_code == 200
    assert r.json()["ship_status"] == "shipped"
    assert r.json()["tracking_number"] == "TRACK-1"


async def test_push_tracking_calls_ebay(auth_client):
    await _seed_sold(auth_client.user_id, confirmed=True)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "GET":
            return httpx.Response(
                200, json={"lineItems": [{"lineItemId": "LI-1"}, {"lineItemId": "LI-2"}]}
            )
        body = json.loads(request.content)
        assert body["trackingNumber"] == "TRACK-9"
        assert body["shippingCarrierCode"] == "USPS"
        assert body["lineItems"] == [{"lineItemId": "LI-1"}, {"lineItemId": "LI-2"}]
        return httpx.Response(201, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        async with AsyncSessionLocal() as db:
            await fulfillment.push_tracking(
                db, auth_client.user_id, "ORDER-X", "TRACK-9", "USPS", client=http
            )
    assert any("shipping_fulfillment" in c for c in calls)
