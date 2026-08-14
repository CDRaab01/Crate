"""Apparel vocabularies, measurement normalization, and archive completeness.

Table-driven per CLAUDE.md §8 — this is the module the archive-first workflow leans on, so
the interesting cases are the honest-null ones: a vision model that skips the block, a tag
that wasn't photographed, a measurement typed in centimetres.
"""

import pytest

from app.apparel import (
    HAND_ONLY_FIELDS,
    LISTING_FIELDS,
    missing_for_listing,
    missing_hand_only,
    normalize_enum,
    normalize_measurements,
)
from app.apparel.attributes import DEPARTMENTS, FITS, SIZE_TYPES, SLEEVE_LENGTHS


@pytest.mark.parametrize(
    "raw,allowed,expected",
    [
        # Exact hits.
        ("mens", DEPARTMENTS, "mens"),
        ("regular", SIZE_TYPES, "regular"),
        ("long", SLEEVE_LENGTHS, "long"),
        ("slim", FITS, "slim"),
        # Shape drift from vision output / hand entry.
        ("Mens", DEPARTMENTS, "mens"),
        ("  WOMENS  ", DEPARTMENTS, "womens"),
        ("Big & Tall", SIZE_TYPES, "big_tall"),
        ("big-tall", SIZE_TYPES, "big_tall"),
        ("three-quarter", SLEEVE_LENGTHS, "three_quarter"),
        # Alias table.
        ("Men", DEPARTMENTS, "mens"),
        ("Women", DEPARTMENTS, "womens"),
        ("female", DEPARTMENTS, "womens"),
        ("Short Sleeve", SLEEVE_LENGTHS, "short"),
        ("Long Sleeve", SLEEVE_LENGTHS, "long"),
        ("loose", FITS, "relaxed"),
        # Rejected: unknown members drop to None rather than storing junk.
        ("XL", DEPARTMENTS, None),
        ("toddler", DEPARTMENTS, None),
        ("banana", SIZE_TYPES, None),
        ("", DEPARTMENTS, None),
        ("   ", DEPARTMENTS, None),
        ("!!!", DEPARTMENTS, None),
        (None, DEPARTMENTS, None),
        # Cross-vocabulary leakage: a valid value from the WRONG enum must not stick.
        ("mens", SIZE_TYPES, None),
        ("petite", DEPARTMENTS, None),
    ],
)
def test_normalize_enum(raw, allowed, expected):
    assert normalize_enum(raw, allowed) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ({"chest": 21, "length": 29}, {"chest": 21.0, "length": 29.0}),
        ({"chest": "21.5"}, {"chest": 21.5}),
        # Unknown keys dropped, known ones kept.
        ({"chest": 21, "collar": 16}, {"chest": 21.0}),
        # Junk values dropped individually, not fatally.
        ({"chest": 21, "length": "about 30"}, {"chest": 21.0}),
        ({"chest": 21, "length": None}, {"chest": 21.0}),
        ({"chest": 21, "waist": 0}, {"chest": 21.0}),
        ({"chest": 21, "waist": -4}, {"chest": 21.0}),
        # Centimetres typed into an inches field — 74cm chest is not a wearable inch value.
        ({"chest": 112}, None),
        ({"chest": 21, "length": 112}, {"chest": 21.0}),
        # "Nothing measured" must be None, never {} — an empty dict reads as work done.
        ({}, None),
        ({"collar": 16}, None),
        (None, None),
        ("21", None),
        ([21], None),
        # Bottoms use a different subset of the same union.
        ({"waist": 17, "inseam": 32, "rise": 11}, {"waist": 17.0, "inseam": 32.0, "rise": 11.0}),
    ],
)
def test_normalize_measurements(raw, expected):
    assert normalize_measurements(raw) == expected


def _clothing(**overrides) -> dict:
    """A fully-specified garment; each test blanks out just what it is about."""
    base = {
        "item_kind": "clothing",
        "brand": "Patagonia",
        "size": "M",
        "size_type": "regular",
        "department": "mens",
        "color": "Navy",
        "material": "100% Organic Cotton",
        "style": "Button-Up",
        "condition": "good",
        "measurements": {"chest": 21.0, "length": 29.0},
    }
    base.update(overrides)
    return base


def test_complete_garment_is_missing_nothing():
    attrs = _clothing()
    assert missing_for_listing(attrs) == []
    assert missing_hand_only(attrs) == []


def test_bare_draft_reports_every_field():
    """A photo-only draft where vision read nothing — the worst case, and the one that
    must nag loudest before the shirt goes in a bin."""
    attrs = {"item_kind": "clothing"}
    assert missing_for_listing(attrs) == list(LISTING_FIELDS)
    assert missing_hand_only(attrs) == list(HAND_ONLY_FIELDS)


def test_hand_only_is_a_subset_of_listing_plus_measurements():
    """Guards the UI contract: one list, with the urgent ones marked inside it."""
    assert set(HAND_ONLY_FIELDS) - {"measurements"} <= set(LISTING_FIELDS)


@pytest.mark.parametrize(
    "blank_field,in_listing,in_hand_only",
    [
        ("size", True, True),
        ("material", True, True),
        ("brand", True, True),
        ("department", True, True),
        ("size_type", True, True),
        # Re-derivable from the stored photos at listing time — a chore, not a loss.
        ("color", True, False),
        ("style", True, False),
        ("condition", True, False),
    ],
)
def test_single_gap_classification(blank_field, in_listing, in_hand_only):
    attrs = _clothing(**{blank_field: None})
    assert (blank_field in missing_for_listing(attrs)) is in_listing
    assert (blank_field in missing_hand_only(attrs)) is in_hand_only


def test_measurements_only_appear_in_hand_only():
    """Measurements aren't an eBay item specific, but they're the least recoverable
    thing in the whole record — tape measure or nothing."""
    attrs = _clothing(measurements=None)
    assert "measurements" not in missing_for_listing(attrs)
    assert "measurements" in missing_hand_only(attrs)


@pytest.mark.parametrize("empty", [None, "", "   ", {}])
def test_blank_shapes_all_count_as_missing(empty):
    """Whitespace and {} are how "someone opened the field and left" arrives."""
    assert "size" in missing_for_listing(_clothing(size=empty if empty != {} else None))
    assert "measurements" in missing_hand_only(_clothing(measurements=empty))


def test_general_goods_are_never_flagged():
    """A fishing lure has no size or department; flagging them would train the user to
    ignore the indicator entirely."""
    attrs = {"item_kind": "general", "brand": "Rapala", "condition": "good"}
    assert missing_for_listing(attrs) == []
    assert missing_hand_only(attrs) == []
    assert missing_for_listing({"item_kind": "general"}) == []
