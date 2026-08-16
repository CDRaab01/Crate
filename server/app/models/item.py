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
# What kind of thing this is, which decides whether the apparel item-specifics apply. Set by
# the vision pass and overridable by hand; "general" is the pre-clothing default so existing
# rows keep their meaning after migration 0003.
ITEM_KINDS = ("clothing", "general")


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

    # --- Apparel item specifics (migration 0003) -----------------------------------------
    # Crate archives a wardrobe long before the eBay keyset exists, so these are captured at
    # photo time and validated by app.apparel: what the tag says (size/material/department)
    # and what a tape measure says (measurements_in) cannot be recovered from a stored photo
    # once the garment is boxed. Free-text where real tags are free-text; enums only where a
    # controlled value is genuinely knowable (see apparel/attributes.py).
    item_kind: Mapped[str] = mapped_column(String(16), default="general", server_default="general")
    size: Mapped[str | None] = mapped_column(String(32), nullable=True)  # tag text: "M", "32x34"
    # What eBay is told. Separate from `size` because eBay enforces a standardized
    # vocabulary (Aug 2026) while the tag says whatever it says — "M/L", "別大",
    # "EUR 30 / US 30". Losing either one loses something that cannot be recovered.
    size_standard: Mapped[str | None] = mapped_column(String(32), nullable=True)
    size_type: Mapped[str | None] = mapped_column(String(16), nullable=True)  # SIZE_TYPES
    department: Mapped[str | None] = mapped_column(String(16), nullable=True)  # DEPARTMENTS
    color: Mapped[str | None] = mapped_column(String(48), nullable=True)
    material: Mapped[str | None] = mapped_column(String(96), nullable=True)  # "60% cotton..."
    style: Mapped[str | None] = mapped_column(String(64), nullable=True)  # "Polo", "Button-Up"
    fit: Mapped[str | None] = mapped_column(String(16), nullable=True)  # FITS
    sleeve_length: Mapped[str | None] = mapped_column(String(16), nullable=True)  # SLEEVE_LENGTHS
    # Inches, garment laid flat, over MEASUREMENT_KEYS. Human-entered only — a vision model
    # cannot measure, and a guessed measurement is a returned item.
    measurements_in: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Where the physical item actually is ("Bin 3", "Closet A shelf 2"). The registry is
    # useless at ship time if a sold shirt can't be found, and that is months away here.
    storage_location: Mapped[str | None] = mapped_column(String(64), nullable=True)

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
    # What this photo is OF (app.apparel.PHOTO_ROLES), set by guided capture. Nullable
    # because photos captured before guided capture existed have no known role — and
    # "unknown" must stay distinguishable from "front", since role decides which photo
    # becomes an eBay listing's gallery image. Never part of a filename: photo_store keys
    # the on-disk names off `order`, so role must not imply a rename.
    role: Mapped[str | None] = mapped_column(String(16), nullable=True)
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
