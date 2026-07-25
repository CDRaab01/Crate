import uuid
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

SHIPPING_PREFERENCES = ("cheapest", "fastest")


class UserSettings(Base):
    """Per-user knobs, seeded with defaults on first login. The price-drop values here are
    what make the unattended drop scheduler 'deterministic policy the user configured'
    (CLAUDE.md §9) — the scheduler reads them, never invents its own."""

    __tablename__ = "user_settings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    # Auto price-drop policy: -drop_step_percent every drop_interval_days, floored at the
    # quick-sale price; drops_enabled=false pauses the scheduler for this user entirely.
    drops_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    drop_interval_days: Mapped[int] = mapped_column(Integer, default=14, server_default="14")
    drop_step_percent: Mapped[Decimal] = mapped_column(
        Numeric(4, 1), default=Decimal("10.0"), server_default="10.0"
    )
    shipping_preference: Mapped[str] = mapped_column(
        String(16), default="cheapest", server_default="cheapest"
    )
    # Override for the compose-pinned default topic; NULL = use the server-wide topic.
    ntfy_topic: Mapped[str | None] = mapped_column(String(128), nullable=True)
