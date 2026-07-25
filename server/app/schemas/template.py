import datetime
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_signature: str
    title_template: str
    description_template: str
    category_id: str | None
    condition_notes: str | None
    last_used_price: Decimal | None
    use_count: int
    last_used_at: datetime.datetime | None


class PriceEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    old_price: Decimal
    new_price: Decimal
    reason: str
    created_at: datetime.datetime
