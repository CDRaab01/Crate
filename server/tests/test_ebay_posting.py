"""Posting path: approve tap → EPS upload → inventory → offer → publish → active.
Every eBay call mocked at the transport (CLAUDE.md §8)."""

import datetime
import re
import uuid
from decimal import Decimal

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
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
        now = datetime.datetime.now(datetime.UTC)
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
    async with httpx.AsyncClient(transport=fake.transport()) as http, AsyncSessionLocal() as db:
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


@pytest.mark.parametrize(
    "kind,condition,expected",
    [
        # Apparel: eBay clothing categories accept only "new" grades + ONE used grade.
        # Publishing USED_GOOD is rejected (errorId 25059) — found on the first real post.
        ("clothing", "good", "USED_EXCELLENT"),
        ("clothing", "fair", "USED_EXCELLENT"),
        ("clothing", "poor", "USED_EXCELLENT"),
        ("clothing", "new", "NEW_WITH_TAGS"),
        # General merchandise keeps the full vocabulary.
        ("general", "good", "USED_GOOD"),
        ("general", "fair", "USED_ACCEPTABLE"),
        ("general", "poor", "FOR_PARTS_OR_NOT_WORKING"),
        ("general", "new", "NEW"),
    ],
)
def test_ebay_condition_respects_apparel_vocabulary(kind, condition, expected):
    item = Item(item_kind=kind, condition=condition)
    assert sell.ebay_condition(item) == expected


def test_used_apparel_is_never_promoted_to_a_new_grade():
    """The collapse must be one-directional.

    Mapping like_new up to NEW_WITHOUT_TAGS would preserve granularity, but "new without
    tags" tells a buyer the garment was never worn — a factual claim about goods someone
    pays for. No used grade may ever map to a NEW_* condition.
    """
    for condition in ("like_new", "good", "fair", "poor"):
        assert not sell.ebay_condition(Item(item_kind="clothing", condition=condition)).startswith(
            "NEW"
        )


def test_unknown_apparel_condition_falls_back_to_a_used_grade():
    """An unrecognised condition must not silently become "new"."""
    assert sell.ebay_condition(Item(item_kind="clothing", condition="wat")) == "USED_EXCELLENT"


def test_apparel_aspects_map_our_vocabularies_to_ebays():
    """attributes.py deferred this mapping until a keyset existed; these are the live values."""
    item = Item(
        item_kind="clothing",
        brand="Lands End",
        color="White",
        size="S",
        size_type="big_tall",
        department="mens",
        material="Cotton",
        style="Polo",
        sleeve_length="long",
        fit="regular",
    )
    aspects = sell.apparel_aspects(item)
    assert aspects["Size"] == ["S"]
    assert aspects["Size Type"] == ["Big & Tall"]  # not "big_tall"
    assert aspects["Department"] == ["Men"]  # not "mens"
    assert aspects["Sleeve Length"] == ["Long Sleeve"]  # not "long"
    assert aspects["Type"] == ["Polo"]
    assert aspects["Color"] == ["White"]


def test_apparel_aspects_omit_unknown_values_rather_than_inventing_them():
    """An item specific is a claim a buyer pays against — a gap is left blank, not guessed."""
    item = Item(item_kind="clothing", size="S", size_type=None, department=None, fit="wat")
    aspects = sell.apparel_aspects(item)
    assert "Size Type" not in aspects
    assert "Department" not in aspects
    assert "Fit" not in aspects  # unrecognised enum is dropped, never passed through raw


def test_general_items_get_no_apparel_aspects():
    assert sell.apparel_aspects(Item(item_kind="general", size="S")) == {}


def test_require_ready_names_every_missing_apparel_specific():
    """eBay fails the publish AFTER creating photos, inventory item and offer. Catching it
    up front is what stops a half-built listing existing on eBay at all."""
    item = Item(
        item_kind="clothing",
        title="Polo",
        chosen_price=Decimal("15.00"),
        condition="good",
        category_id="185101",
        photos=[ItemPhoto(order=0, original_path="/x.png")],
        brand="Lands End",
        color=None,
        size="S",
        size_type=None,
        department="mens",
    )
    with pytest.raises(HTTPException) as exc:
        sell._require_ready(item)
    assert "color" in exc.value.detail
    assert "size type" in exc.value.detail
    assert "brand" not in exc.value.detail  # present, must not be reported missing


def test_existing_offer_id_is_recovered_from_ebays_25002():
    """A publish that fails leaves eBay holding the offer. Every retry then collides with it,
    so the id has to come back out of the error or the listing can never be completed."""
    resp = httpx.Response(
        400,
        json={
            "errors": [
                {
                    "errorId": 25002,
                    "message": "A user error has occurred. Offer entity already exists.",
                    "parameters": [{"name": "offerId", "value": "11447191010"}],
                }
            ]
        },
    )
    assert sell._existing_offer_id(resp) == "11447191010"


def test_a_different_25002_without_an_offer_id_is_not_adopted():
    """errorId 25002 covers several 'user error' conditions — the offerId parameter is what
    identifies this one. Matching on the message text would break when eBay rewords it."""
    resp = httpx.Response(
        400,
        json={
            "errors": [
                {
                    "errorId": 25002,
                    "message": "A user error has occurred. The item specific Size is missing.",
                    "parameters": [{"name": "0", "value": "Size is missing"}],
                }
            ]
        },
    )
    assert sell._existing_offer_id(resp) is None


def test_unrelated_errors_are_not_mistaken_for_an_existing_offer():
    resp = httpx.Response(400, json={"errors": [{"errorId": 25059, "message": "Bad condition"}]})
    assert sell._existing_offer_id(resp) is None


def test_non_json_error_body_does_not_raise():
    """eBay 5xx pages are HTML; the adoption check must not turn that into a parse error."""
    assert sell._existing_offer_id(httpx.Response(502, text="<html>gateway</html>")) is None
