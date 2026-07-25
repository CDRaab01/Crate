import datetime
import uuid
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Status lifecycle (transitions live in the item service, never in clients):
#   draft -> active -> sold -> shipped, plus returned / delisted.
ITEM_STATUSES = ("draft", "active", "sold", "shipped", "returned", "delisted")
ITEM_CONDITIONS = ("new", "like_new", "good", "fair", "poor")


class Item(Base):
    __tablename__ = "items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Nullable identification fields: a freshly-captured draft has photos and nothing else;
    # the vision pipeline fills these in and the user confirms at review time.
    title: Mapped[str | None] = mapped_column(String(80), nullable=True)  # eBay title cap
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Brand/model feed the duplicate-template signature (Phase 3) and item specifics; kept as
    # columns (an addition over the CLAUDE.md §4 sketch, flagged in ARCHITECTURE.md) because
    # template creation at sale time needs them long after the vision draft is gone.
    brand: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category_id: Mapped[str | None] = mapped_column(String(32), nullable=True)  # eBay category
    condition: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft", server_default="draft")

    quick_sale_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    patient_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    chosen_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", server_default="USD")

    ebay_listing_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ebay_offer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # AI estimate from photos at listing time; confirmed (editable) at ship time before rates
    # are quoted. dims_in_est is {"l": .., "w": .., "h": ..} in inches.
    weight_oz_est: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    dims_in_est: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    weight_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("duplicate_templates.id", ondelete="SET NULL"), nullable=True
    )
    date_listed: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Scan-pipeline state: NULL processed_at = identification still running (or dead — see
    # scan_error). The review stack polls until this is set.
    processed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scan_error: Mapped[str | None] = mapped_column(String(255), nullable=True)

    photos = relationship(
        "ItemPhoto",
        back_populates="item",
        order_by="ItemPhoto.order",
        cascade="all, delete-orphan",
        lazy="raise",
    )


class ItemPhoto(Base):
    __tablename__ = "item_photos"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    order: Mapped[int] = mapped_column(Integer, default=0)
    # Binaries live on the /data/photos volume; the DB stores paths only.
    original_path: Mapped[str] = mapped_column(String(512))
    cleaned_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # eBay Picture Services URL after upload (Phase 5).
    ebay_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    item = relationship("Item", back_populates="photos", lazy="raise")

    @property
    def cleaned(self) -> bool:
        """Schema-facing flag: has the cleanup pass produced output for this photo yet?"""
        return self.cleaned_path is not None
