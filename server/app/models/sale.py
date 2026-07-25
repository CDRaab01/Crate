import datetime
import uuid
from decimal import Decimal

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

SHIP_STATUSES = ("pending", "label_bought", "shipped", "delivered")


class Sale(Base):
    __tablename__ = "sales"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    ebay_order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    sale_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    fees: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    sale_date: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    buyer_username: Mapped[str] = mapped_column(String(128))
    # Most sensitive data in the suite so far: tailnet-only exposure, minimum-payload rule.
    buyer_address: Mapped[dict] = mapped_column(JSON)
    ship_status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending"
    )
    tracking_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    carrier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    service: Mapped[str | None] = mapped_column(String(64), nullable=True)
    label_cost: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    label_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
