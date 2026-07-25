import datetime
import uuid
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

PRICE_EVENT_REASONS = ("auto_drop", "manual", "floor_reached")


class PriceEvent(Base):
    """History for the price-drop scheduler and the UI. Every unattended drop is logged here
    (and ntfy-notified) — that audit trail is part of what makes the automatic scheduler an
    acceptable exception to the user-confirmed-writes rule (CLAUDE.md §9)."""

    __tablename__ = "price_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    old_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    new_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    reason: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
