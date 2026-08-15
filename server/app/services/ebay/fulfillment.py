"""Order + buyer-message polling (Crate polls OUT on a scheduler — no inbound webhooks,
consistent with tailnet-only; eBay never calls in).

Idempotency contracts: `sales.ebay_order_id` and `buyer_messages.ebay_message_id` are
unique — a poll cycle can re-see the same order/message forever without duplicating.
A detected sale drives the lifecycle transition (active → sold), which is also what
mints the duplicate template, then pings ntfy.
"""

import datetime
import logging
import re
import uuid
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.buyer_message import BuyerMessage
from app.models.item import Item
from app.models.sale import Sale
from app.models.user_settings import UserSettings
from app.services import item_lifecycle, notify
from app.services.ebay import oauth

logger = logging.getLogger(__name__)

_TRADING_HOSTS = {
    "production": "https://api.ebay.com/ws/api.dll",
    "sandbox": "https://api.sandbox.ebay.com/ws/api.dll",
}


async def _user_topic(db: AsyncSession, user_id) -> str | None:
    row = (
        await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    ).scalar_one_or_none()
    return row.ntfy_topic if row else None


async def poll_orders(db: AsyncSession, user_id, client: httpx.AsyncClient | None = None) -> int:
    """Pull recent orders; new ones become sales + sold items + an ntfy ping.
    Returns how many NEW sales landed."""
    token = await oauth.user_token(db, user_id, client=client)
    owns = client is None
    active = client or httpx.AsyncClient(timeout=30.0)
    try:
        # Last 7 days is plenty for a 15-minute poller and keeps the response bounded.
        since = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=7)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
        resp = await active.get(
            f"{oauth.api_host()}/sell/fulfillment/v1/order",
            params={"filter": f"creationdate:[{since}..]", "limit": "50"},
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        body = resp.json()
    finally:
        if owns:
            await active.aclose()

    new_sales = 0
    for order in body.get("orders", []):
        order_id = order.get("orderId")
        if not order_id:
            continue
        existing = (
            await db.execute(select(Sale).where(Sale.ebay_order_id == order_id))
        ).scalar_one_or_none()
        if existing is not None:
            continue

        line_items = order.get("lineItems", [])
        if not line_items:
            continue
        sku = line_items[0].get("sku") or ""
        try:
            sku_uuid = uuid.UUID(sku)
        except ValueError:
            logger.warning("order %s carries a non-Crate sku %r — skipping", order_id, sku)
            continue
        matched = (
            await db.execute(select(Item).where(Item.user_id == user_id, Item.id == sku_uuid))
        ).scalar_one_or_none()
        if matched is None:
            logger.warning("order %s references unknown sku %r — skipping", order_id, sku)
            continue

        ship_to = (
            (order.get("fulfillmentStartInstructions") or [{}])[0]
            .get("shippingStep", {})
            .get("shipTo", {})
        )
        total = order.get("pricingSummary", {}).get("total", {}).get("value")
        try:
            sale_price = Decimal(str(total))
        except (InvalidOperation, TypeError):
            sale_price = matched.chosen_price or Decimal(0)

        sale = Sale(
            item_id=matched.id,
            ebay_order_id=order_id,
            sale_price=sale_price,
            sale_date=datetime.datetime.now(datetime.UTC),
            buyer_username=str(order.get("buyer", {}).get("username") or "unknown"),
            # Minimum payload we actually need to ship — nothing more (CLAUDE.md §9).
            buyer_address={
                "name": ship_to.get("fullName"),
                "address": ship_to.get("contactAddress"),
                "phone": (ship_to.get("primaryPhone") or {}).get("phoneNumber"),
            },
        )
        db.add(sale)
        if matched.status == "active":
            await item_lifecycle.transition(db, matched, "sold")
        await db.commit()
        new_sales += 1

        await notify.push(
            "Sold on eBay 🎉",
            f"{matched.title or 'An item'} sold for ${sale_price} — "
            "open Crate to confirm weight and buy the label.",
            topic=await _user_topic(db, user_id),
            priority="high",
        )
    return new_sales


async def poll_messages(db: AsyncSession, user_id, client: httpx.AsyncClient | None = None) -> int:
    """Pull buyer message headers (Trading GetMyMessages, ReturnHeaders detail — subjects
    only in v1: Crate flags, it doesn't chat; replies happen in the eBay app).
    Returns how many NEW messages were flagged."""
    token = await oauth.user_token(db, user_id, client=client)
    xml_request = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<GetMyMessagesRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
        "<DetailLevel>ReturnHeaders</DetailLevel>"
        "</GetMyMessagesRequest>"
    )
    owns = client is None
    active = client or httpx.AsyncClient(timeout=30.0)
    try:
        resp = await active.post(
            _TRADING_HOSTS.get(settings.ebay_environment, _TRADING_HOSTS["sandbox"]),
            headers={
                "X-EBAY-API-COMPATIBILITY-LEVEL": "1193",
                "X-EBAY-API-CALL-NAME": "GetMyMessages",
                "X-EBAY-API-SITEID": "0",
                "X-EBAY-API-IAF-TOKEN": token,
                "Content-Type": "text/xml",
            },
            content=xml_request,
        )
        resp.raise_for_status()
        text = resp.text
    finally:
        if owns:
            await active.aclose()

    new_messages = 0
    for message_xml in re.findall(r"<Message>(.*?)</Message>", text, re.DOTALL):
        message_id = _tag(message_xml, "MessageID")
        if not message_id:
            continue
        exists = (
            await db.execute(select(BuyerMessage).where(BuyerMessage.ebay_message_id == message_id))
        ).scalar_one_or_none()
        if exists is not None:
            continue

        subject = _tag(message_xml, "Subject") or "(no subject)"
        listing_id = _tag(message_xml, "ItemID")
        item = None
        if listing_id:
            item = (
                await db.execute(
                    select(Item).where(Item.user_id == user_id, Item.ebay_listing_id == listing_id)
                )
            ).scalar_one_or_none()

        message_type = "return_request" if "return" in subject.lower() else "question"
        db.add(
            BuyerMessage(
                item_id=item.id if item else None,
                ebay_message_id=message_id,
                message_type=message_type,
                content=subject,
            )
        )
        await db.commit()
        new_messages += 1

        await notify.push(
            "eBay buyer message",
            subject if item is None else f"{item.title}: {subject}",
            topic=await _user_topic(db, user_id),
        )
    return new_messages


async def push_tracking(
    db: AsyncSession,
    user_id,
    order_id: str,
    tracking_number: str,
    carrier: str,
    client: httpx.AsyncClient | None = None,
) -> None:
    """Attach tracking to the eBay order (side effect of a user-initiated label purchase —
    one of the two sanctioned unattended write paths, CLAUDE.md §9)."""
    token = await oauth.user_token(db, user_id, client=client)
    owns = client is None
    active = client or httpx.AsyncClient(timeout=30.0)
    try:
        order_resp = await active.get(
            f"{oauth.api_host()}/sell/fulfillment/v1/order/{order_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        order_resp.raise_for_status()
        line_item_ids = [
            {"lineItemId": li["lineItemId"]}
            for li in order_resp.json().get("lineItems", [])
            if li.get("lineItemId")
        ]
        resp = await active.post(
            f"{oauth.api_host()}/sell/fulfillment/v1/order/{order_id}/shipping_fulfillment",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "lineItems": line_item_ids,
                "shippedDate": datetime.datetime.now(datetime.UTC).strftime(
                    "%Y-%m-%dT%H:%M:%S.000Z"
                ),
                "shippingCarrierCode": carrier,
                "trackingNumber": tracking_number,
            },
        )
        if resp.status_code not in (200, 201, 204):
            raise httpx.HTTPStatusError(
                f"tracking push rejected ({resp.status_code})",
                request=resp.request,
                response=resp,
            )
    finally:
        if owns:
            await active.aclose()


def _tag(xml_fragment: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>([^<]*)</{tag}>", xml_fragment)
    return match.group(1).strip() if match else None
