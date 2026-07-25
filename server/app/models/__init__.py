# Import every model here so Alembic's env.py sees the full metadata.
from app.models.buyer_message import BuyerMessage
from app.models.duplicate_template import DuplicateTemplate
from app.models.ebay_credentials import EbayCredentials
from app.models.item import Item, ItemPhoto
from app.models.price_event import PriceEvent
from app.models.sale import Sale
from app.models.user import User
from app.models.user_settings import UserSettings

__all__ = [
    "BuyerMessage",
    "DuplicateTemplate",
    "EbayCredentials",
    "Item",
    "ItemPhoto",
    "PriceEvent",
    "Sale",
    "User",
    "UserSettings",
]
