"""Auto price-drop policy: pure math table + the scheduler cycle with its guardrails
(the CLAUDE.md §9 documented exception — deterministic, floored, logged, notified)."""

import datetime
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.item import Item
from app.models.price_event import PriceEvent
from app.models.user import User
from app.models.user_settings import UserSettings
from app.pricing.drops import DropPlan, next_price, plan_drop
from app.services import drop_scheduler, notify

D = Decimal
NOW = datetime.datetime(2026, 7, 25, 12, 0, tzinfo=datetime.timezone.utc)


def days_ago(n: int) -> datetime.datetime:
    return NOW - datetime.timedelta(days=n)


# ── pure math ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "current,step,floor,expected",
    [
        (D("20.00"), D("10"), D("12.00"), D("18.00")),  # plain 10% step
        (D("13.00"), D("10"), D("12.00"), D("12.00")),  # clamped to floor
        (D("12.00"), D("10"), D("12.00"), D("12.00")),  # already at floor
        (D("19.99"), D("10"), D("1.00"), D("17.99")),  # cent rounding (17.991 → 17.99)
        (D("10.00"), D("50"), D("1.00"), D("5.00")),  # max sane step
    ],
)
def test_next_price(current, step, floor, expected):
    assert next_price(current, step, floor) == expected


BASE = dict(
    chosen_price=D("20.00"),
    quick_sale_price=D("12.00"),
    step_percent=D("10"),
    interval_days=14,
    now=NOW,
    floor_prompted=False,
)


def test_plan_drop_due():
    plan = plan_drop(**{**BASE, "last_change_at": days_ago(15)})
    assert plan == DropPlan("drop", D("18.00"))


def test_plan_not_due():
    assert plan_drop(**{**BASE, "last_change_at": days_ago(13)}).action == "none"


def test_plan_floor_prompt_once():
    at_floor = {**BASE, "chosen_price": D("12.00"), "last_change_at": days_ago(15)}
    assert plan_drop(**at_floor).action == "floor_prompt"
    assert plan_drop(**{**at_floor, "floor_prompted": True}).action == "none"


def test_plan_unpriced_items_left_alone():
    assert (
        plan_drop(**{**BASE, "chosen_price": None, "last_change_at": days_ago(99)}).action == "none"
    )
    assert (
        plan_drop(**{**BASE, "quick_sale_price": None, "last_change_at": days_ago(99)}).action
        == "none"
    )


# ── the scheduler cycle ───────────────────────────────────────────────────────


async def _seed(
    status="active", *, chosen="20.00", quick="12.00", listed_days_ago=15, enabled=True
):
    async with AsyncSessionLocal() as db:
        user = User(name="D", email=f"drop_{uuid.uuid4().hex[:8]}@crate.test")
        db.add(user)
        await db.flush()
        db.add(UserSettings(user_id=user.id, drops_enabled=enabled))
        item = Item(
            user_id=user.id,
            title=f"Droppable {uuid.uuid4().hex[:8]}",
            status=status,
            chosen_price=D(chosen),
            quick_sale_price=D(quick),
            patient_price=D("20.00"),
            ebay_offer_id="OFFER-D",
            date_listed=days_ago(listed_days_ago),
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return item


@pytest.fixture
def offer_updates(monkeypatch):
    updated: list[tuple] = []

    async def fake_update(db, item, client=None):
        updated.append((item.id, item.chosen_price))

    monkeypatch.setattr(drop_scheduler.sell, "update_offer_price", fake_update)
    return updated


@pytest.fixture
def ntfy_recorder(monkeypatch):
    sent: list[str] = []

    async def fake_push(title, body, *, topic=None, priority="default", client=None):
        sent.append((title, body))
        return True

    monkeypatch.setattr(notify, "push", fake_push)
    return sent


async def test_drop_cycle_applies_and_logs(offer_updates, ntfy_recorder):
    item = await _seed()
    totals = await drop_scheduler.drop_cycle(now=NOW)
    assert totals["dropped"] >= 1

    async with AsyncSessionLocal() as db:
        stored = (await db.execute(select(Item).where(Item.id == item.id))).scalar_one()
        assert stored.chosen_price == D("18.00")
        event = (
            await db.execute(select(PriceEvent).where(PriceEvent.item_id == item.id))
        ).scalar_one()
        assert event.reason == "auto_drop"
        assert event.old_price == D("20.00") and event.new_price == D("18.00")
    assert (item.id, D("18.00")) in offer_updates
    assert any(t == "Price dropped" and item.title in b for t, b in ntfy_recorder)

    # Second pass the same day: interval hasn't elapsed since the event — no double drop.
    await drop_scheduler.drop_cycle(now=NOW)
    async with AsyncSessionLocal() as db:
        events = (
            (await db.execute(select(PriceEvent).where(PriceEvent.item_id == item.id)))
            .scalars()
            .all()
        )
        assert len(events) == 1


async def test_floor_prompt_fires_once(offer_updates, ntfy_recorder):
    item = await _seed(chosen="12.00")
    await drop_scheduler.drop_cycle(now=NOW)
    later = NOW + datetime.timedelta(days=30)
    await drop_scheduler.drop_cycle(now=later)

    async with AsyncSessionLocal() as db:
        events = (
            (await db.execute(select(PriceEvent).where(PriceEvent.item_id == item.id)))
            .scalars()
            .all()
        )
        assert [e.reason for e in events] == ["floor_reached"]
    floor_pings = [
        (t, b) for t, b in ntfy_recorder if t == "At the floor, still unsold" and item.title in b
    ]
    assert len(floor_pings) == 1
    # A floor prompt never touches eBay (other tests' leftover actives may drop, so filter).
    assert not any(updated_id == item.id for updated_id, _ in offer_updates)


async def test_disabled_user_skipped(offer_updates, ntfy_recorder):
    item = await _seed(enabled=False)
    await drop_scheduler.drop_cycle(now=NOW)
    async with AsyncSessionLocal() as db:
        stored = (await db.execute(select(Item).where(Item.id == item.id))).scalar_one()
        assert stored.chosen_price == D("20.00")
    assert not any(updated_id == item.id for updated_id, _ in offer_updates)


async def test_ebay_failure_leaves_no_local_trace(monkeypatch, ntfy_recorder):
    item = await _seed()

    async def dead_update(db, item, client=None):
        raise RuntimeError("eBay down")

    monkeypatch.setattr(drop_scheduler.sell, "update_offer_price", dead_update)
    totals = await drop_scheduler.drop_cycle(now=NOW)
    assert totals["dropped"] == 0  # every drop path goes through the (dead) eBay update

    async with AsyncSessionLocal() as db:
        stored = (await db.execute(select(Item).where(Item.id == item.id))).scalar_one()
        # Rolled back: the live listing and local state still agree; next pass retries.
        assert stored.chosen_price == D("20.00")
        events = (
            (await db.execute(select(PriceEvent).where(PriceEvent.item_id == item.id)))
            .scalars()
            .all()
        )
        assert events == []


async def test_settings_roundtrip_and_bounds(auth_client):
    r = await auth_client.get("/settings")
    assert r.status_code == 200
    assert r.json()["drop_interval_days"] == 14

    r = await auth_client.patch(
        "/settings",
        json={"drop_interval_days": 7, "drop_step_percent": "15", "shipping_preference": "fastest"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["drop_interval_days"] == 7
    assert body["shipping_preference"] == "fastest"

    r = await auth_client.patch("/settings", json={"drop_step_percent": "95"})
    assert r.status_code == 422  # a 95% daily drop is a typo, not a strategy
    r = await auth_client.patch("/settings", json={"shipping_preference": "teleport"})
    assert r.status_code == 422
