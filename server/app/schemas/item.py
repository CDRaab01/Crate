import datetime
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.item import ITEM_CONDITIONS, ITEM_STATUSES


class Dims(BaseModel):
    l: float = Field(gt=0, le=120)  # noqa: E741 — l/w/h is the natural shipping vocabulary
    w: float = Field(gt=0, le=120)
    h: float = Field(gt=0, le=120)


class ItemPhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order: int
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

    def validated_condition(self) -> str | None:
        if self.condition is not None and self.condition not in ITEM_CONDITIONS:
            raise ValueError(f"condition must be one of {ITEM_CONDITIONS}")
        return self.condition


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
