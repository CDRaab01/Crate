"""Pricing orchestration: pick a query for the item, pull comps, compute both prices.

The pipeline calls price_item() best-effort — unconfigured or eBay-down means a draft
without prices, never a dead draft. The /comps endpoint reuses build_query/search so the
review UI's evidence matches what priced the item.
"""

import logging

import httpx

from app.models.item import Item
from app.pricing import browse
from app.pricing.comps import Comp, PriceSuggestion, compute_prices

logger = logging.getLogger(__name__)


def build_query(item: Item) -> str | None:
    """Brand+model is the sharpest query; fall back to the title. None ⇒ nothing to search."""
    if item.brand or item.model:
        return " ".join(part for part in (item.brand, item.model) if part)
    return item.title or None


async def fetch_comps(item: Item, client: httpx.AsyncClient | None = None) -> list[Comp]:
    query = build_query(item)
    if query is None:
        return []
    return await browse.search_active_comps(query, item.condition, client=client)


async def price_item(item: Item, client: httpx.AsyncClient | None = None) -> PriceSuggestion | None:
    """Set quick/patient on the item from fresh active comps. Best-effort by design."""
    if not browse.configured():
        return None
    try:
        comps = await fetch_comps(item, client=client)
    except httpx.HTTPError:
        logger.warning("comp search failed for item %s", item.id, exc_info=True)
        return None
    suggestion = compute_prices(comps)
    if suggestion is None:
        return None
    item.quick_sale_price = suggestion.quick_sale
    item.patient_price = suggestion.patient
    return suggestion
