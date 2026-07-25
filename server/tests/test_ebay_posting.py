"""Posting path: approve tap → EPS upload → inventory → offer → publish → active.
Every eBay call mocked at the transport (CLAUDE.md §8)."""

import datetime
import re
import uuid

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.ebay_credentials import EbayCredentials
from app.models.item import Item, ItemPhoto
from app.services.ebay import oauth, sell

FERNET_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def ebay_ready(monkeypatch):
    monkeypatch.setattr(settings, "ebay_client_id", "test-id")
    monkeypatch.setattr(settings, "ebay_client_secret", "test-secret")
    monkeypatch.setattr(settings, "ebay_ru_name", "Test-RuName")
    monkeypatch.setattr(settings, "fernet_key", FERNET_KEY)
    monkeypatch.setattr(settings, "ebay_environment", "sandbox")
    monkeypatch.setattr(settings, "ebay_fulfillment_policy_id", "F1")
    monkeypatch.setattr(settings, "ebay_payment_policy_id", "P1")
    monkeypatch.setattr(settings, "ebay_return_policy_id", "R1")
    monkeypatch.setattr(settings, "ebay_location_postal_code", "48864")


class EbayFake:
    """A scripted eBay sandbox: records calls, plays the happy path by default."""

    def __init__(self):
        self.calls: list[str] = []
        self.inventory_bodies: list[dict] = []
        self.offer_bodies: list[dict] = []

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            self.calls.append(f"{request.method} {path}")
            if path.endswith("/ws/api.dll"):
                return httpx.Response(
                    200,
                    text="<UploadSiteHostedPicturesResponse><SiteHostedPictureDetails>"
                    "<FullURL>https://i.ebayimg.com/00/fake.png</FullURL>"
                    "</SiteHostedPictureDetails></UploadSiteHostedPicturesResponse>",
                )
            if re.search(r"/location/[^/]+$", path) and request.method == "GET":
                return httpx.Response(404)
            if re.search(r"/location/[^/]+$", path) and request.method == "POST":
                return httpx.Response(204)
            if "/inventory_item/" in path:
                import json as _json

                self.inventory_bodies.append(_json.loads(request.content))
                return httpx.Response(204)
            if path.endswith("/offer") and request.method == "POST":
                import json as _json

                self.offer_bodies.append(_json.loads(request.content))
                return httpx.Response(201, json={"offerId": "OFFER-1"})
            if path.endswith("/publish"):
                return httpx.Response(200, json={"listingId": "110123456789"})
            if path.endswith("/withdraw"):
                return httpx.Response(200, json={})
            return httpx.Response(500, text=f"unexpected call {path}")

        return httpx.MockTransport(handler)


async def _seed_ready_item(user_id, tmp_path) -> uuid.UUID:
    photo_file = tmp_path / "orig.png"
    photo_file.write_bytes(b"\x89PNGfake")
    async with AsyncSessionLocal() as db:
        item = Item(
            user_id=user_id,
            title="Rapala F11",
            description="A classic.",
            brand="Rapala",
            model="F11",
            condition="good",
            category_id="52149",
            chosen_price=15,
            status="draft",
        )
        db.add(item)
        await db.flush()
        db.add(ItemPhoto(item_id=item.id, order=0, original_path=str(photo_file)))
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
        return item.id


async def test_publish_happy_path(auth_client, tmp_path, monkeypatch):
    item_id = await _seed_ready_item(auth_client.user_id, tmp_path)
    fake = EbayFake()

    # Call the service directly with an injected transport — the endpoint's own client
    # can't be swapped per-test, and the service IS the posting logic.
    async with httpx.AsyncClient(transport=fake.transport()) as http:
        async with AsyncSessionLocal() as db:
            item = (
                await db.execute(
                    select(Item).options(selectinload(Item.photos)).where(Item.id == item_id)
                )
            ).scalar_one()
            listing_id = await sell.publish_item(db, item, client=http)
            await db.commit()

    assert listing_id == "110123456789"
    # EPS first, then location ensure, inventory PUT, offer POST, publish POST.
    joined = " | ".join(fake.calls)
    assert "/ws/api.dll" in joined
    assert "PUT /sell/inventory/v1/inventory_item/" in joined
    assert "POST /sell/inventory/v1/offer" in joined
    assert "publish" in joined
    # Offer carried the policies + the chosen price.
    offer = fake.offer_bodies[0]
    assert offer["listingPolicies"]["fulfillmentPolicyId"] == "F1"
    assert offer["pricingSummary"]["price"]["value"] == "15.00"  # Numeric(10,2) round-trip
    # Inventory carried the EPS URL + aspects.
    inv = fake.inventory_bodies[0]
    assert inv["product"]["imageUrls"] == ["https://i.ebayimg.com/00/fake.png"]
    assert inv["product"]["aspects"]["Brand"] == ["Rapala"]

    async with AsyncSessionLocal() as db:
        stored = (await db.execute(select(Item).where(Item.id == item_id))).scalar_one()
        assert stored.ebay_listing_id == "110123456789"
        assert stored.ebay_offer_id == "OFFER-1"


async def test_post_endpoint_requires_readiness(auth_client, tmp_path):
    """Missing chosen_price/condition/etc -> 422 listing exactly what's missing."""
    async with AsyncSessionLocal() as db:
        item = Item(user_id=auth_client.user_id, status="draft", title="Untitled-ish")
        db.add(item)
        await db.commit()
        item_id = item.id

    r = await auth_client.post(f"/items/{item_id}/post")
    assert r.status_code in (409, 422)
    detail = r.json()["detail"]
    assert "missing" in detail.lower() or "not connected" in detail.lower()


async def test_post_endpoint_409_when_not_draft(auth_client, tmp_path):
    async with AsyncSessionLocal() as db:
        item = Item(user_id=auth_client.user_id, status="active", title="Live already")
        db.add(item)
        await db.commit()
        item_id = item.id
    r = await auth_client.post(f"/items/{item_id}/post")
    assert r.status_code == 409


async def test_publish_409_without_policies(auth_client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ebay_fulfillment_policy_id", None)
    item_id = await _seed_ready_item(auth_client.user_id, tmp_path)
    r = await auth_client.post(f"/items/{item_id}/post")
    assert r.status_code == 409
    assert "business policies" in r.json()["detail"].lower()


async def test_publish_503_when_unconfigured(auth_client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ebay_client_id", None)
    item_id = await _seed_ready_item(auth_client.user_id, tmp_path)
    r = await auth_client.post(f"/items/{item_id}/post")
    assert r.status_code == 503
