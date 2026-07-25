import datetime
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.buyer_message import BuyerMessage
from app.models.item import Item
from app.security import CurrentUser

router = APIRouter(prefix="/messages", tags=["messages"])


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_id: uuid.UUID | None
    message_type: str
    content: str
    flagged_at: datetime.datetime
    resolved: bool


async def _owned_message(db: AsyncSession, user_id, message_id: uuid.UUID) -> BuyerMessage:
    """Messages attach to items (or to nobody, pre-sale) — ownership rides the item when
    present; unattached messages are visible to every user of this single-user app."""
    message = (
        await db.execute(select(BuyerMessage).where(BuyerMessage.id == message_id))
    ).scalar_one_or_none()
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    if message.item_id is not None:
        item = (
            await db.execute(
                select(Item).where(Item.id == message.item_id, Item.user_id == user_id)
            )
        ).scalar_one_or_none()
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    return message


@router.get("", response_model=list[MessageOut])
async def inbox(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    unresolved_only: bool = False,
):
    """The flag inbox: unresolved first, newest first. Replies happen in the eBay app —
    Crate flags, it doesn't chat (v1)."""
    query = select(BuyerMessage).order_by(
        BuyerMessage.resolved.asc(), BuyerMessage.flagged_at.desc()
    )
    if unresolved_only:
        query = query.where(BuyerMessage.resolved.is_(False))
    rows = (await db.execute(query)).scalars().all()
    # Filter attached messages to the caller's items.
    owned_item_ids = set(
        (await db.execute(select(Item.id).where(Item.user_id == user.id))).scalars().all()
    )
    return [m for m in rows if m.item_id is None or m.item_id in owned_item_ids]


@router.post("/{message_id}/resolve", response_model=MessageOut)
async def resolve(
    message_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    message = await _owned_message(db, user.id, message_id)
    message.resolved = True
    await db.commit()
    return message
