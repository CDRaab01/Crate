"""Order/message poller: idempotent sale + message ingestion, lifecycle + template side
effects, ntfy pings. eBay + ntfy fully mocked (CLAUDE.md §8)."""

import datetime
import uuid
from decimal import Decimal

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.buyer_message import BuyerMessage
from app.models.duplicate_template import DuplicateTemplate
from app.models.ebay_credentials import EbayCredentials
from app.models.item import Item
from app.models.sale import Sale
from app.services import notify
from app.services.ebay import fulfillment, oauth

FERNET_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def ebay_ready(monkeypatch):
    monkeypatch.setattr(settings, "ebay_client_id", "test-id")
    monkeypatch.setattr(settings, "ebay_client_secret", "test-secret")
    monkeypatch.setattr(settings, "ebay_ru_name", "Test-RuName")
    monkeypatch.setattr(settings, "fernet_key", FERNET_KEY)
    monkeypatch.setattr(settings, "ebay_environment", "sandbox")


@pytest.fixture
def ntfy_recorder(monkeypatch):
    sent: list[tuple[str, str]] = []

    async def fake_push(title, body, *, topic=None, priority="default", client=None):
        sent.append((title, body))
        return True

    monkeypatch.setattr(notify, "push", fake_push)
    # fulfillment imported `notify` as a module, so patching the module function works.
    return sent


async def _seed_active_item(user_id) -> Item:
    async with AsyncSessionLocal() as db:
        item = Item(
            user_id=user_id,
            title="Rapala F11",
            brand="Rapala",
            model="F11",
            condition="good",
            status="active",
            chosen_price=Decimal("15.00"),
            ebay_listing_id=f"11000{uuid.uuid4().hex[:8]}",
        )
        db.add(item)
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
        await db.refresh(item)
        return item


def orders_transport(item: Item, order_id: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/sell/fulfillment/v1/order" in request.url.path
        return httpx.Response(
            200,
            json={
                "orders": [
                    {
                        "orderId": order_id,
                        "buyer": {"username": "fish4life"},
                        "pricingSummary": {"total": {"value": "17.55"}},
                        "lineItems": [{"sku": str(item.id)}],
                        "fulfillmentStartInstructions": [
                            {
                                "shippingStep": {
                                    "shipTo": {
                                        "fullName": "Pat Buyer",
                                        "contactAddress": {
                                            "addressLine1": "1 Fish Rd",
                                            "city": "Lansing",
                                            "stateOrProvince": "MI",
                                            "postalCode": "48864",
                                            "countryCode": "US",
                                        },
                                    }
                                }
                            }
                        ],
                    },
                    {"orderId": f"{order_id}-junk", "lineItems": [{"sku": "not-a-crate-sku"}]},
                ]
            },
        )

    return httpx.MockTransport(handler)


async def test_sale_detected_once_and_side_effects(auth_client, ntfy_recorder):
    item = await _seed_active_item(auth_client.user_id)
    order_id = f"ORDER-{uuid.uuid4().hex[:10]}"

    async with httpx.AsyncClient(transport=orders_transport(item, order_id)) as http:
        async with AsyncSessionLocal() as db:
            assert await fulfillment.poll_orders(db, auth_client.user_id, client=http) == 1
        # Second poll re-sees the same order — idempotent by ebay_order_id.
        async with AsyncSessionLocal() as db:
            assert await fulfillment.poll_orders(db, auth_client.user_id, client=http) == 0

    async with AsyncSessionLocal() as db:
        sale = (await db.execute(select(Sale).where(Sale.ebay_order_id == order_id))).scalar_one()
        assert sale.sale_price == Decimal("17.55")
        assert sale.buyer_username == "fish4life"
        assert sale.buyer_address["name"] == "Pat Buyer"
        assert sale.ship_status == "pending"

        stored = (await db.execute(select(Item).where(Item.id == item.id))).scalar_one()
        assert stored.status == "sold"
        # The sold transition minted the duplicate template.
        template = (
            await db.execute(
                select(DuplicateTemplate).where(DuplicateTemplate.user_id == auth_client.user_id)
            )
        ).scalar_one()
        assert template.item_signature == "rapala f11"

    assert len(ntfy_recorder) == 1
    assert "Sold" in ntfy_recorder[0][0]

    # The Ship-screen read works.
    r = await auth_client.get(f"/items/{item.id}/sale")
    assert r.status_code == 200
    assert r.json()["buyer_address"]["name"] == "Pat Buyer"


def messages_xml(msg1: str, msg2: str, listing_id: str) -> str:
    return (
        '<?xml version="1.0"?>'
        "<GetMyMessagesResponse><Messages>"
        f"<Message><MessageID>{msg1}</MessageID><Subject>Will this ship to Alaska?</Subject>"
        f"<ItemID>{listing_id}</ItemID></Message>"
        f"<Message><MessageID>{msg2}</MessageID><Subject>Return request for order</Subject></Message>"
        "</Messages></GetMyMessagesResponse>"
    )


async def test_messages_flagged_once_and_inbox(auth_client, ntfy_recorder):
    item = await _seed_active_item(auth_client.user_id)
    msg1, msg2 = f"MSG-{uuid.uuid4().hex[:10]}", f"MSG-{uuid.uuid4().hex[:10]}"
    xml = messages_xml(msg1, msg2, item.ebay_listing_id)

    transport = httpx.MockTransport(lambda req: httpx.Response(200, text=xml))
    async with httpx.AsyncClient(transport=transport) as http:
        async with AsyncSessionLocal() as db:
            assert await fulfillment.poll_messages(db, auth_client.user_id, client=http) == 2
        async with AsyncSessionLocal() as db:
            assert await fulfillment.poll_messages(db, auth_client.user_id, client=http) == 0

    async with AsyncSessionLocal() as db:
        flagged = (
            (await db.execute(select(BuyerMessage).order_by(BuyerMessage.ebay_message_id)))
            .scalars()
            .all()
        )
        by_id = {m.ebay_message_id: m for m in flagged if m.ebay_message_id in (msg1, msg2)}
        assert by_id[msg1].item_id == item.id  # matched via ebay_listing_id
        assert by_id[msg1].message_type == "question"
        assert by_id[msg2].item_id is None  # pre-sale / unmatched
        assert by_id[msg2].message_type == "return_request"

    # Inbox + resolve round-trip.
    r = await auth_client.get("/messages", params={"unresolved_only": "true"})
    assert r.status_code == 200
    inbox = r.json()
    assert {m["content"] for m in inbox} >= {"Will this ship to Alaska?"}
    msg_id = inbox[0]["id"]
    r = await auth_client.post(f"/messages/{msg_id}/resolve")
    assert r.status_code == 200 and r.json()["resolved"] is True


async def test_ntfy_push_silently_off_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "ntfy_base_url", None)
    assert await notify.push("t", "b") is False


async def test_ntfy_push_posts_with_topic_override(monkeypatch):
    monkeypatch.setattr(settings, "ntfy_base_url", "https://ntfy.example")
    monkeypatch.setattr(settings, "ntfy_topic", "crate-default")

    rec: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        rec["url"] = str(request.url)
        rec["title"] = request.headers.get("title")
        rec["body"] = request.content.decode()
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        assert await notify.push("Sold!", "body", topic="my-topic", client=http) is True
    assert rec["url"].endswith("/my-topic")  # per-user override wins
    assert rec["title"] == "Sold!"


async def test_poll_once_covers_all_connected_users(auth_client, monkeypatch, ntfy_recorder):
    from app.services import poller

    item = await _seed_active_item(auth_client.user_id)
    calls: list[str] = []

    async def fake_orders(db, user_id, client=None):
        calls.append(f"orders:{user_id}")
        return 1

    async def fake_messages(db, user_id, client=None):
        calls.append(f"messages:{user_id}")
        return 0

    monkeypatch.setattr(poller.fulfillment, "poll_orders", fake_orders)
    monkeypatch.setattr(poller.fulfillment, "poll_messages", fake_messages)

    totals = await poller.poll_once()
    assert totals["sales"] >= 1
    assert any(c.startswith("orders:") for c in calls)
    assert any(c.startswith("messages:") for c in calls)
    assert item is not None  # keep the reference honest
