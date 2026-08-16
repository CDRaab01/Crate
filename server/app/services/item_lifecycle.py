"""Item status transitions — the ONE place lifecycle rules live (CLAUDE.md §4).

Clients display, never compute; routers and schedulers call `transition()` and never
assign `item.status` directly. The sold transition is also where duplicate templates are
born: an item that actually sold is a proven listing pattern worth reusing.
"""

import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.matching.signature import signature_for_item
from app.models.duplicate_template import DuplicateTemplate
from app.models.item import Item

# state -> the states it may legally move to. Deletion isn't a transition (draft/delisted
# rows are removed outright); "returned" is terminal pending a human decision to relist.
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft": ("active",),
    "active": ("sold", "delisted"),
    "sold": ("shipped", "returned"),
    "shipped": ("returned",),
    "returned": ("active",),
    "delisted": ("active",),
}


class IllegalTransition(ValueError):
    def __init__(self, current: str, requested: str):
        super().__init__(f"can't move an item from {current!r} to {requested!r}")
        self.current = current
        self.requested = requested


async def transition(db: AsyncSession, item: Item, new_status: str) -> Item:
    """Apply a legal status change + its side effects. Caller commits."""
    if new_status not in ALLOWED_TRANSITIONS.get(item.status, ()):
        raise IllegalTransition(item.status, new_status)

    now = datetime.datetime.now(datetime.UTC)
    if new_status == "active":
        item.date_listed = now
    if new_status == "sold":
        await _upsert_template(db, item, now)

    item.status = new_status
    return item


async def _upsert_template(db: AsyncSession, item: Item, now: datetime.datetime) -> None:
    """A sold item becomes (or refreshes) a duplicate template — the reuse-on-capture
    fast path. No signature ⇒ nothing to match on later ⇒ no template (for clothing that
    means no brand or no size — see build_apparel_signature)."""
    signature = signature_for_item(item)
    if signature is None or not item.title:
        return

    existing = (
        await db.execute(
            select(DuplicateTemplate).where(
                DuplicateTemplate.user_id == item.user_id,
                DuplicateTemplate.item_signature == signature,
            )
        )
    ).scalar_one_or_none()

    price = item.chosen_price
    if existing is not None:
        existing.title_template = item.title
        existing.description_template = item.description or existing.description_template
        existing.category_id = item.category_id or existing.category_id
        if price is not None:
            existing.last_used_price = price
        existing.use_count += 1
        existing.last_used_at = now
        item.template_id = existing.id
    else:
        template = DuplicateTemplate(
            user_id=item.user_id,
            item_signature=signature,
            title_template=item.title,
            description_template=item.description or "",
            category_id=item.category_id,
            condition_notes=None,
            last_used_price=price,
            use_count=1,
            last_used_at=now,
        )
        db.add(template)
        await db.flush()
        item.template_id = template.id
