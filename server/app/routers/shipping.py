"""The sale → shipped flow: confirm weight → shop rates → buy label → tracking pushed.

The confirm step is deliberate (locked decision): the AI's weight/dims guess pre-fills
the Ship screen but rates are never quoted, and money never moves, until the human has
confirmed the numbers — wrong-weight labels cost real money.
"""

import logging
import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.limiter import limiter
from app.models.item import Item
from app.models.sale import Sale
from app.models.user_settings import UserSettings
from app.schemas.item import Dims, ItemOut, SaleOut
from app.security import CurrentUser
from app.services import item_lifecycle, notify, shippo
from app.services.ebay import fulfillment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/items", tags=["shipping"])


class WeightConfirm(BaseModel):
    weight_oz: Decimal = Field(gt=0, le=2400)
    dims_in: Dims


class RateOut(BaseModel):
    rate_id: str
    provider: str
    service: str
    amount: Decimal
    currency: str
    estimated_days: int | None


class BuyLabelRequest(BaseModel):
    """The quoted rate the user picked — carrier/service/amount ride along because the
    Shippo transaction echoes the rate only as an id."""

    rate_id: str
    provider: str
    service: str
    amount: Decimal = Field(ge=0)


async def _sold_item_and_sale(db: AsyncSession, user_id, item_id: uuid.UUID) -> tuple[Item, Sale]:
    item = (
        await db.execute(
            select(Item)
            .options(selectinload(Item.photos))
            .where(Item.id == item_id, Item.user_id == user_id)
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    if item.status not in ("sold", "shipped"):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Item isn't sold yet (status={item.status!r})"
        )
    sale = (await db.execute(select(Sale).where(Sale.item_id == item_id))).scalar_one_or_none()
    if sale is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Sold item has no sale record")
    return item, sale


@router.post("/{item_id}/confirm-weight", response_model=ItemOut)
async def confirm_weight(
    item_id: uuid.UUID,
    req: WeightConfirm,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """The human checkpoint: the AI guess arrives pre-filled, the confirmed numbers are
    what rates get quoted against."""
    item, _ = await _sold_item_and_sale(db, user.id, item_id)
    item.weight_oz_est = req.weight_oz.quantize(Decimal("0.01"))
    item.dims_in_est = req.dims_in.model_dump()
    item.weight_confirmed = True
    await db.commit()
    return item


@router.get("/{item_id}/rates", response_model=list[RateOut])
@limiter.limit("30/minute")
async def rates(
    request: Request,
    item_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    item, sale = await _sold_item_and_sale(db, user.id, item_id)
    if not item.weight_confirmed or item.weight_oz_est is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Confirm the weight/dimensions first — rates are quoted against confirmed numbers",
        )
    quotes = await shippo.get_rates(sale.buyer_address, item.weight_oz_est, item.dims_in_est)

    prefs = (
        await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    ).scalar_one_or_none()
    preference = prefs.shipping_preference if prefs else "cheapest"
    if preference == "fastest":
        quotes.sort(key=lambda r: (r.estimated_days is None, r.estimated_days, r.amount))
    else:
        quotes.sort(key=lambda r: r.amount)
    return [RateOut(**r.__dict__) for r in quotes]


@router.post("/{item_id}/buy-label", response_model=SaleOut)
@limiter.limit("10/minute")
async def buy_label(
    request: Request,
    item_id: uuid.UUID,
    req: BuyLabelRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """One explicit tap buys the label (REAL MONEY), pushes tracking to the eBay order,
    and flips the lifecycle to shipped. Tracking push failure is logged and surfaced but
    doesn't unbuy the label — the label exists either way."""
    item, sale = await _sold_item_and_sale(db, user.id, item_id)
    if sale.ship_status not in ("pending",):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Label already handled (ship_status={sale.ship_status!r})"
        )

    label = await shippo.buy_label(req.rate_id)
    sale.tracking_number = label.tracking_number
    sale.label_url = label.label_url
    sale.carrier = req.provider
    sale.service = req.service
    sale.label_cost = req.amount
    sale.ship_status = "label_bought"
    await db.commit()

    tracking_pushed = True
    try:
        await fulfillment.push_tracking(
            db, user.id, sale.ebay_order_id, label.tracking_number, req.provider
        )
    except Exception:
        # The label is bought and real; a failed tracking push must not lose that state.
        logger.exception("tracking push failed for order %s", sale.ebay_order_id)
        tracking_pushed = False

    sale.ship_status = "shipped"
    if item.status == "sold":
        await item_lifecycle.transition(db, item, "shipped")
    await db.commit()

    await notify.push(
        "Label bought 📦",
        f"{item.title or 'Item'}: {req.provider} {req.service} for ${req.amount}."
        + ("" if tracking_pushed else " (Tracking push to eBay FAILED — add it manually.)"),
    )
    return sale
