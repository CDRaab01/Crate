"""Pure pricing math — exhaustively unit-tested, no I/O (CLAUDE.md §4/§9).

Reality constraint baked into the design: sold-comp data (Marketplace Insights) is
partner-only, so these are ACTIVE-market prices and the UI labels them honestly:

- patient    = median of the trimmed active comps (what the market is asking)
- quick-sale = undercut the cheapest credible active comp (be the best deal listed)

"Credible" = survives IQR outlier trimming, which kills both the $1 parts-only listing
and the $999 hopeful before they poison either number.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

# Undercut factor for quick-sale: 5% under the cheapest credible active.
QUICK_UNDERCUT = Decimal("0.95")
PRICE_FLOOR = Decimal("1.00")
# Below this many comps, trimming is meaningless — use the raw set.
MIN_COMPS_FOR_TRIM = 4


@dataclass(frozen=True)
class Comp:
    title: str
    price: Decimal
    condition: str | None
    url: str | None


@dataclass(frozen=True)
class PriceSuggestion:
    quick_sale: Decimal
    patient: Decimal
    comp_count: int  # comps that survived trimming — the evidence base


def _quantize(value: Decimal) -> Decimal:
    return max(PRICE_FLOOR, value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def trim_outliers(prices: list[Decimal]) -> list[Decimal]:
    """IQR trim (1.5×): drops the $1 parts listing and the $999 hopeful. Small sets pass
    through untouched — with n < 4 the quartiles are noise."""
    if len(prices) < MIN_COMPS_FOR_TRIM:
        return sorted(prices)
    ordered = sorted(prices)
    n = len(ordered)
    q1 = ordered[n // 4]
    q3 = ordered[(3 * n) // 4] if (3 * n) // 4 < n else ordered[-1]
    iqr = q3 - q1
    lo = q1 - iqr * Decimal("1.5")
    hi = q3 + iqr * Decimal("1.5")
    return [p for p in ordered if lo <= p <= hi]


def compute_prices(comps: list[Comp]) -> PriceSuggestion | None:
    """Both price points from active comps, or None when there's no usable evidence."""
    prices = [c.price for c in comps if c.price > 0]
    if not prices:
        return None
    trimmed = trim_outliers(prices)
    if not trimmed:
        return None

    patient = _quantize(Decimal(median(trimmed)))
    quick = _quantize(min(trimmed[0] * QUICK_UNDERCUT, patient))
    return PriceSuggestion(quick_sale=quick, patient=patient, comp_count=len(trimmed))
