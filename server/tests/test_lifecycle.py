"""Status-transition matrix + the sold->template side effect."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.duplicate_template import DuplicateTemplate
from app.models.item import ITEM_STATUSES, Item
from app.models.user import User
from app.services.item_lifecycle import ALLOWED_TRANSITIONS, IllegalTransition, transition

LEGAL = [(src, dst) for src, dsts in ALLOWED_TRANSITIONS.items() for dst in dsts]
ILLEGAL = [
    (src, dst)
    for src in ITEM_STATUSES
    for dst in ITEM_STATUSES
    if dst not in ALLOWED_TRANSITIONS.get(src, ()) and src != dst
]


async def _user_and_item(db, status="draft", **kwargs) -> tuple[User, Item]:
    user = User(name="T", email=f"lc_{uuid.uuid4().hex[:8]}@crate.test")
    db.add(user)
    await db.flush()
    item = Item(user_id=user.id, status=status, **kwargs)
    db.add(item)
    await db.flush()
    return user, item


@pytest.mark.parametrize("src,dst", LEGAL)
async def test_legal_transitions(src, dst):
    async with AsyncSessionLocal() as db:
        _, item = await _user_and_item(db, status=src, title="Thing", brand="B", model="M")
        await transition(db, item, dst)
        assert item.status == dst
        await db.rollback()


@pytest.mark.parametrize("src,dst", ILLEGAL)
async def test_illegal_transitions_raise(src, dst):
    async with AsyncSessionLocal() as db:
        _, item = await _user_and_item(db, status=src)
        with pytest.raises(IllegalTransition):
            await transition(db, item, dst)
        await db.rollback()


async def test_activation_stamps_date_listed():
    async with AsyncSessionLocal() as db:
        _, item = await _user_and_item(db, status="draft")
        assert item.date_listed is None
        await transition(db, item, "active")
        assert item.date_listed is not None
        await db.rollback()


async def test_sold_creates_template_and_second_sale_bumps_it():
    async with AsyncSessionLocal() as db:
        user, item = await _user_and_item(
            db,
            status="active",
            title="Rapala Original Floater F11",
            description="Classic balsa minnow.",
            brand="Rapala",
            model="F11",
            category_id="52149",
            chosen_price=Decimal("14.00"),
        )
        await transition(db, item, "sold")
        await db.commit()

        template = (
            await db.execute(select(DuplicateTemplate).where(DuplicateTemplate.user_id == user.id))
        ).scalar_one()
        assert template.item_signature == "rapala f11"
        assert template.use_count == 1
        assert template.last_used_price == Decimal("14.00")
        assert item.template_id == template.id

        # Same model sells again at a new price -> same template, refreshed (case-insensitive
        # match; note a HYPHENATED "F-11" would tokenize differently — documented looseness
        # covered in test_signature).
        item2 = Item(
            user_id=user.id,
            status="active",
            title="Rapala Original Floater F11 (silver)",
            brand="rapala",
            model="f11",
            chosen_price=Decimal("15.50"),
        )
        db.add(item2)
        await db.flush()
        await transition(db, item2, "sold")
        await db.commit()

        templates = (
            (
                await db.execute(
                    select(DuplicateTemplate).where(DuplicateTemplate.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(templates) == 1
        assert templates[0].use_count == 2
        assert templates[0].last_used_price == Decimal("15.50")
        assert item2.template_id == templates[0].id


async def test_sold_without_brand_or_model_creates_no_template():
    async with AsyncSessionLocal() as db:
        user, item = await _user_and_item(db, status="active", title="Mystery box of cables")
        await transition(db, item, "sold")
        await db.commit()
        count = (
            (
                await db.execute(
                    select(DuplicateTemplate).where(DuplicateTemplate.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert count == []
