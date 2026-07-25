"""Pure price-drop policy math (CLAUDE.md §9's documented exception).

The scheduler may write to eBay unattended ONLY because this is deterministic policy the
user configured (interval/step in settings), never AI output: it never goes below the
user-approved quick-sale floor, every drop is ntfy-notified and logged in price_events.
Keep it pure, bounded, and boring — this module has no I/O on purpose.
"""

import datetime
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True)
class DropPlan:
    """What the scheduler should do with one item right now."""

    action: str  # "drop" | "floor_prompt" | "none"
    new_price: Decimal | None = None


def next_price(current: Decimal, step_percent: Decimal, floor: Decimal) -> Decimal:
    """One step down, clamped to the floor, cent-quantized."""
    stepped = current * (Decimal(100) - step_percent) / Decimal(100)
    return max(floor, stepped.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def plan_drop(
    *,
    chosen_price: Decimal | None,
    quick_sale_price: Decimal | None,
    step_percent: Decimal,
    interval_days: int,
    last_change_at: datetime.datetime,
    now: datetime.datetime,
    floor_prompted: bool,
) -> DropPlan:
    """Decide drop / floor-prompt / nothing for one active listing.

    - No prices ⇒ nothing (an item priced by hand without comps has no floor to respect,
      so the scheduler leaves it alone entirely — conservative by design).
    - Interval not elapsed since the last change (listing date or latest price event) ⇒
      nothing.
    - Above the floor ⇒ drop one step (clamped).
    - At/below the floor ⇒ prompt hold/relist/delist ONCE (floor_prompted latches).
    """
    if chosen_price is None or quick_sale_price is None:
        return DropPlan("none")
    if interval_days <= 0:
        return DropPlan("none")
    if now - last_change_at < datetime.timedelta(days=interval_days):
        return DropPlan("none")

    floor = quick_sale_price
    if chosen_price > floor:
        return DropPlan("drop", next_price(chosen_price, step_percent, floor))
    if not floor_prompted:
        return DropPlan("floor_prompt")
    return DropPlan("none")
