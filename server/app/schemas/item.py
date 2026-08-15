import datetime
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.apparel import (
    DEPARTMENTS,
    FITS,
    SIZE_TYPES,
    SLEEVE_LENGTHS,
    attrs_from_item,
    missing_for_listing,
    missing_hand_only,
    missing_photo_roles,
    normalize_enum,
    normalize_measurements,
)
from app.models.item import ITEM_CONDITIONS, ITEM_KINDS, ITEM_STATUSES


class Measurements(BaseModel):
    """Inches, garment laid flat. Every field optional — a top has no inseam and a partly
    measured garment is still worth recording."""

    model_config = ConfigDict(extra="forbid")

    chest: float | None = Field(default=None, gt=0, le=90)
    length: float | None = Field(default=None, gt=0, le=90)
    sleeve: float | None = Field(default=None, gt=0, le=90)
    shoulder: float | None = Field(default=None, gt=0, le=90)
    waist: float | None = Field(default=None, gt=0, le=90)
    inseam: float | None = Field(default=None, gt=0, le=90)
    rise: float | None = Field(default=None, gt=0, le=90)


class Dims(BaseModel):
    l: float = Field(gt=0, le=120)  # noqa: E741 — l/w/h is the natural shipping vocabulary
    w: float = Field(gt=0, le=120)
    h: float = Field(gt=0, le=120)


class ItemPhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order: int
    # What this photo is of, when guided capture said so. None for anything captured before
    # roles existed — the client should badge that as unknown, not assume "front".
    role: str | None = None
    cleaned: bool
    ebay_url: str | None


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    description: str | None
    brand: str | None
    model: str | None
    category_id: str | None
    condition: str | None
    status: str
    item_kind: str
    size: str | None
    size_type: str | None
    department: str | None
    color: str | None
    material: str | None
    style: str | None
    fit: str | None
    sleeve_length: str | None
    measurements_in: dict | None
    storage_location: str | None
    quick_sale_price: Decimal | None
    patient_price: Decimal | None
    chosen_price: Decimal | None
    currency: str
    ebay_listing_id: str | None
    weight_oz_est: Decimal | None
    dims_in_est: dict | None
    weight_confirmed: bool
    template_id: uuid.UUID | None
    date_listed: datetime.datetime | None
    created_at: datetime.datetime
    processed_at: datetime.datetime | None
    scan_error: str | None
    photos: list[ItemPhotoOut] = []

    # Computed server-side, per CLAUDE.md §9 ("clients display, never compute") — the review
    # stack and registry both badge these, and two implementations would drift.
    @computed_field
    @property
    def missing_for_listing(self) -> list[str]:
        """Apparel specifics eBay will want that are still empty ([] for general goods)."""
        return missing_for_listing(attrs_from_item(self))

    @computed_field
    @property
    def missing_hand_only(self) -> list[str]:
        """The urgent subset: gaps needing the physical garment back in hand."""
        return missing_hand_only(attrs_from_item(self))

    @computed_field
    @property
    def missing_photo_roles(self) -> list[str]:
        """Photo roles a garment still needs — separate from the field gaps above because
        the remedy is a camera, not a text field. The client renders it in the same row."""
        return missing_photo_roles([p.role for p in self.photos], self.item_kind)


class ItemUpdate(BaseModel):
    """Review-stack edits. PATCH clearing convention (suite-wide): omitted/None = untouched,
    "" = clear (for nullable text fields)."""

    title: str | None = Field(default=None, max_length=80)
    description: str | None = None
    brand: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=64)
    category_id: str | None = Field(default=None, max_length=32)
    condition: str | None = None
    chosen_price: Decimal | None = Field(default=None, ge=0)
    weight_oz_est: Decimal | None = Field(default=None, gt=0, le=2400)
    dims_in_est: Dims | None = None
    weight_confirmed: bool | None = None

    # Apparel specifics. Free-text fields follow the same ""-clears convention as title etc.
    item_kind: str | None = None
    size: str | None = Field(default=None, max_length=32)
    size_type: str | None = None
    department: str | None = None
    color: str | None = Field(default=None, max_length=48)
    material: str | None = Field(default=None, max_length=96)
    style: str | None = Field(default=None, max_length=64)
    fit: str | None = None
    sleeve_length: str | None = None
    measurements_in: Measurements | None = None
    storage_location: str | None = Field(default=None, max_length=64)

    def validated_condition(self) -> str | None:
        if self.condition is not None and self.condition not in ITEM_CONDITIONS:
            raise ValueError(f"condition must be one of {ITEM_CONDITIONS}")
        return self.condition

    def validated_enums(self) -> dict[str, str]:
        """Check the apparel vocabularies, returning the normalized values to apply.

        Rejects rather than silently dropping (unlike the vision path, which degrades): a
        hand edit that types an unknown size type should say so, not vanish into a NULL the
        user believes they filled in.
        """
        checked = {
            "item_kind": (self.item_kind, ITEM_KINDS),
            "size_type": (self.size_type, SIZE_TYPES),
            "department": (self.department, DEPARTMENTS),
            "fit": (self.fit, FITS),
            "sleeve_length": (self.sleeve_length, SLEEVE_LENGTHS),
        }
        out: dict[str, str] = {}
        for name, (raw, allowed) in checked.items():
            if raw is None or raw == "":  # omitted, or the ""-clears sentinel
                continue
            value = normalize_enum(raw, allowed)
            if value is None:
                raise ValueError(f"{name} must be one of {allowed}")
            out[name] = value
        return out

    def validated_measurements(self) -> dict | None:
        """Normalize the tape-measure payload; an all-empty body clears the field."""
        if self.measurements_in is None:
            return None
        return normalize_measurements(self.measurements_in.model_dump())


class SaleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_id: uuid.UUID
    ebay_order_id: str
    sale_price: Decimal
    fees: Decimal | None
    sale_date: datetime.datetime
    buyer_username: str
    buyer_address: dict
    ship_status: str
    tracking_number: str | None
    carrier: str | None
    service: str | None
    label_cost: Decimal | None
    label_url: str | None


class CompOut(BaseModel):
    title: str
    price: Decimal
    condition: str | None
    url: str | None


class CompsOut(BaseModel):
    """Evidence for the review screen: honest active-market framing, top comps with links."""

    comps: list[CompOut]
    quick_sale: Decimal | None
    patient: Decimal | None
    comp_count: int


class ScanAccepted(BaseModel):
    """POST /items/scan response: the draft exists immediately; identification fills in
    asynchronously (poll GET /items/{id} until processed_at is set)."""

    id: uuid.UUID
    status: str
    photo_count: int


STATUSES = ITEM_STATUSES
