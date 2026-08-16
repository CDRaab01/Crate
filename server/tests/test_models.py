"""Repo-layer smoke: the §4 schema round-trips through SQLAlchemy against real Postgres."""

import datetime
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.models import Item, ItemPhoto, PriceEvent, Sale, User


async def test_item_lifecycle_round_trip():
    async with AsyncSessionLocal() as db:
        user = User(name="Seller", email=f"model_{uuid.uuid4().hex[:8]}@example.com")
        db.add(user)
        await db.flush()

        item = Item(
            user_id=user.id,
            title="Vintage fishing lure",
            condition="good",
            quick_sale_price=Decimal("12.00"),
            patient_price=Decimal("19.50"),
            dims_in_est={"l": 4, "w": 2, "h": 2},
        )
        db.add(item)
        await db.flush()
        db.add_all(
            [
                ItemPhoto(item_id=item.id, order=0, original_path="/data/photos/a.jpg"),
                ItemPhoto(item_id=item.id, order=1, original_path="/data/photos/b.jpg"),
            ]
        )
        db.add(
            PriceEvent(
                item_id=item.id,
                old_price=Decimal("19.50"),
                new_price=Decimal("17.55"),
                reason="auto_drop",
            )
        )
        db.add(
            Sale(
                item_id=item.id,
                ebay_order_id=f"order-{uuid.uuid4().hex[:10]}",
                sale_price=Decimal("17.55"),
                sale_date=datetime.datetime.now(datetime.UTC),
                buyer_username="fish4life",
                buyer_address={"name": "B", "city": "Lansing", "state": "MI"},
            )
        )
        await db.commit()

        loaded = (
            await db.execute(
                select(Item).options(selectinload(Item.photos)).where(Item.id == item.id)
            )
        ).scalar_one()
        assert loaded.status == "draft"
        assert [p.order for p in loaded.photos] == [0, 1]
        assert loaded.quick_sale_price == Decimal("12.00")


async def test_photo_cascade_deletes_with_item():
    async with AsyncSessionLocal() as db:
        user = User(name="S", email=f"cascade_{uuid.uuid4().hex[:8]}@example.com")
        db.add(user)
        await db.flush()
        item = Item(user_id=user.id)
        db.add(item)
        await db.flush()
        db.add(ItemPhoto(item_id=item.id, order=0, original_path="/data/photos/x.jpg"))
        await db.commit()
        item_id = item.id

        await db.delete(
            (
                await db.execute(
                    select(Item).options(selectinload(Item.photos)).where(Item.id == item_id)
                )
            ).scalar_one()
        )
        await db.commit()

        photos = (
            (await db.execute(select(ItemPhoto).where(ItemPhoto.item_id == item_id)))
            .scalars()
            .all()
        )
        assert photos == []
