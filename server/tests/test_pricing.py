"""Exhaustive tests for the pure pricing math (CLAUDE.md §4: 'clients display, never
compute' — this module is the ONLY place quick/patient numbers come from)."""

from decimal import Decimal

import pytest

from app.pricing.comps import (
    Comp,
    compute_prices,
    trim_outliers,
)

D = Decimal


def comps(*prices: str) -> list[Comp]:
    return [Comp(title=f"comp {p}", price=D(p), condition="USED", url=None) for p in prices]


# ── trim_outliers ─────────────────────────────────────────────────────────────


def test_small_sets_pass_through_untrimmed():
    assert trim_outliers([D("1.00"), D("999.00")]) == [D("1.00"), D("999.00")]
    assert trim_outliers([D("5"), D("6"), D("7")]) == [D("5"), D("6"), D("7")]


def test_iqr_trim_drops_parts_listing_and_hopeful():
    prices = [D("1.00"), D("18"), D("19"), D("20"), D("21"), D("22"), D("999.00")]
    trimmed = trim_outliers(prices)
    assert D("1.00") not in trimmed
    assert D("999.00") not in trimmed
    assert D("20") in trimmed


def test_uniform_prices_survive_trimming():
    prices = [D("10")] * 6
    assert trim_outliers(prices) == prices


def test_empty_input():
    assert trim_outliers([]) == []


# ── compute_prices ────────────────────────────────────────────────────────────


def test_no_comps_returns_none():
    assert compute_prices([]) is None
    assert compute_prices(comps()) is None


def test_zero_and_negative_prices_ignored():
    assert compute_prices([Comp("free", D("0"), None, None)]) is None


def test_patient_is_median_quick_undercuts_cheapest():
    s = compute_prices(comps("18", "19", "20", "21", "22"))
    assert s is not None
    assert s.patient == D("20.00")
    # cheapest credible = 18 → 18 * 0.95 = 17.10
    assert s.quick_sale == D("17.10")
    assert s.comp_count == 5


def test_quick_never_exceeds_patient():
    # Two comps, no trimming: cheapest*0.95 could exceed the median with a weird spread —
    # the min() clamp keeps quick <= patient always.
    s = compute_prices(comps("10", "10"))
    assert s is not None
    assert s.quick_sale <= s.patient


def test_outliers_do_not_poison_either_number():
    s = compute_prices(comps("1.00", "18", "19", "20", "21", "22", "999"))
    assert s is not None
    # Without trimming, quick would be 0.95; with it, the $1 listing is gone.
    assert s.quick_sale == D("17.10")
    assert s.patient == D("20.00")
    assert s.comp_count == 5


def test_floor_at_one_dollar():
    s = compute_prices(comps("0.50", "1.00", "1.05"))
    assert s is not None
    assert s.quick_sale >= D("1.00")


@pytest.mark.parametrize(
    "prices,patient",
    [
        (("10", "20", "30"), D("20.00")),  # odd count -> middle
        (("10", "20", "30", "40"), D("25.00")),  # even count -> mean of middles
        (("9.99",), D("9.99")),  # single comp: patient = it, quick undercuts it
    ],
)
def test_median_semantics(prices, patient):
    s = compute_prices(comps(*prices))
    assert s is not None
    assert s.patient == patient
