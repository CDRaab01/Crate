"""The daily stale-listing pass: apply the user's configured drop policy to every active
listing, push the new price to eBay, log it, notify.

This is the ONE unattended eBay write path (plus tracking upload) — sanctioned because
the policy is deterministic user configuration, floored at the user-approved quick-sale
price, logged in price_events, and ntfy-notified per drop (CLAUDE.md §9)."""

import datetime
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.item import Item
from app.models.price_event import PriceEvent
from app.models.user_settings import UserSettings
from app.pricing.drops import plan_drop
from app.services import notify
from app.services.ebay import sell

logger = logging.getLogger(__name__)


async def _last_change_at(db: AsyncSession, item: Item) -> datetime.datetime:
    latest_event = (
        await db.execute(
            select(PriceEvent.created_at)
            .where(PriceEvent.item_id == item.id)
            .order_by(PriceEvent.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    candidates = [t for t in (item.date_listed, latest_event) if t is not None]
    return max(candidates) if candidates else item.created_at


async def _floor_prompted(db: AsyncSession, item: Item) -> bool:
    return (
        await db.execute(
            select(PriceEvent.id)
            .where(PriceEvent.item_id == item.id, PriceEvent.reason == "floor_reached")
            .limit(1)
        )
    ).scalar_one_or_none() is not None


async def drop_cycle(now: datetime.datetime | None = None) -> dict:
    """One pass over all active listings. Each item gets its own session so a rollback
    (eBay rejected the update) can't poison the rest of the pass. Returns counts."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    totals = {"dropped": 0, "floor_prompts": 0}

    async with AsyncSessionLocal() as db:
        item_ids = (
            (await db.execute(select(Item.id).where(Item.status == "active"))).scalars().all()
        )

    for item_id in item_ids:
        async with AsyncSessionLocal() as db:
            item = (await db.execute(select(Item).where(Item.id == item_id))).scalar_one_or_none()
            if item is None or item.status != "active":
                continue
            settings_row = (
                await db.execute(select(UserSettings).where(UserSettings.user_id == item.user_id))
            ).scalar_one_or_none()
            if settings_row is None or not settings_row.drops_enabled:
                continue

            plan = plan_drop(
                chosen_price=item.chosen_price,
                quick_sale_price=item.quick_sale_price,
                step_percent=settings_row.drop_step_percent,
                interval_days=settings_row.drop_interval_days,
                last_change_at=await _last_change_at(db, item),
                now=now,
                floor_prompted=await _floor_prompted(db, item),
            )

            try:
                if plan.action == "drop":
                    old_price = item.chosen_price
                    item.chosen_price = plan.new_price
                    # eBay first: if the offer update fails, nothing is recorded locally
                    # and the next cycle retries — local state never lies about the
                    # live listing.
                    await sell.update_offer_price(db, item)
                    db.add(
                        PriceEvent(
                            item_id=item.id,
                            old_price=old_price,
                            new_price=plan.new_price,
                            reason="auto_drop",
                        )
                    )
                    await db.commit()
                    totals["dropped"] += 1
                    await notify.push(
                        "Price dropped",
                        f"{item.title or 'Item'}: ${old_price} → ${plan.new_price} "
                        f"(floor ${item.quick_sale_price}).",
                        topic=settings_row.ntfy_topic,
                    )
                elif plan.action == "floor_prompt":
                    db.add(
                        PriceEvent(
                            item_id=item.id,
                            old_price=item.chosen_price,
                            new_price=item.chosen_price,
                            reason="floor_reached",
                        )
                    )
                    await db.commit()
                    totals["floor_prompts"] += 1
                    await notify.push(
                        "At the floor, still unsold",
                        f"{item.title or 'Item'} has sat at its quick-sale floor "
                        f"(${item.chosen_price}) for a full interval. Open Crate to "
                        "hold, relist fresh, or delist.",
                        topic=settings_row.ntfy_topic,
                        priority="high",
                    )
            except Exception:
                # NOTE: use item_id, not item.id — the rollback expires the ORM object and
                # touching it again would raise MissingGreenlet inside the handler.
                await db.rollback()
                logger.exception("drop cycle failed for item %s; will retry next pass", item_id)
    return totals
