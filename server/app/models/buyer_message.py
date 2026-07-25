import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

MESSAGE_TYPES = ("question", "return_request", "other")


class BuyerMessage(Base):
    __tablename__ = "buyer_messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Nullable: messages can arrive pre-sale (a question about an active listing) or fail to
    # match a known item at all.
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ebay_message_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    message_type: Mapped[str] = mapped_column(String(20), default="other", server_default="other")
    content: Mapped[str] = mapped_column(Text)
    flagged_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
