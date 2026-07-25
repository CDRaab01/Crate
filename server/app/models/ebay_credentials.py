import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EbayCredentials(Base):
    """Per-user eBay OAuth token store (one row per user).

    Tokens are ENCRYPTED AT REST (Fernet, key from server/.env — Phase 5 service concern);
    the *_enc columns hold ciphertext, never raw tokens. Refresh tokens last ~18 months —
    the app surfaces expiry well before it hits.
    """

    __tablename__ = "ebay_credentials"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    access_token_enc: Mapped[str] = mapped_column(Text)
    refresh_token_enc: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    refresh_expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    environment: Mapped[str] = mapped_column(
        String(16), default="sandbox", server_default="sandbox"
    )
    scopes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
