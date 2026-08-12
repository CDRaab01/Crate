"""Table-driven tests for the pure signature module (CLAUDE.md §9: matching math is
centralized, pure, and exhaustively tested)."""

import pytest

from app.matching.signature import (
    build_apparel_signature,
    build_signature,
    signature_for_item,
)

CASES = [
    # (brand, model, expected)
    ("Rapala", "F11", "rapala f11"),
    ("rapala", "f11", "rapala f11"),  # casefolded
    ("RAPALA", "F-11", "rapala f 11"),  # punctuation splits tokens
    ("Rapala®", "F11", "rapala f11"),  # symbols stripped
    ("Nike", "Air Max 90", "nike air max 90"),
    ("Nike Nike", "Nike Air", "nike air"),  # deduped, order-stable
    ("  Rapala  ", None, "rapala"),  # model-less brand still matches
    (None, "F11", "f11"),
    (None, None, None),  # nothing identifying -> no signature
    ("", "", None),
    ("®™", "!!!", None),  # symbols only -> no tokens -> no signature
    ("Lego", "75192 Millennium Falcon", "lego 75192 millennium falcon"),
]


@pytest.mark.parametrize("brand,model,expected", CASES)
def test_build_signature(brand, model, expected):
    assert build_signature(brand, model) == expected


def test_capture_and_sale_time_signatures_agree():
    """The invariant that makes templates work: the signature computed at capture time
    (fresh vision draft) equals the one computed at sale time (stored columns)."""
    draft_brand, draft_model = "Rapala", "F11"
    stored_brand, stored_model = "Rapala", "F11"
    assert build_signature(draft_brand, draft_model) == build_signature(stored_brand, stored_model)


# --- Clothing signatures ---------------------------------------------------------------
# Garments seldom have a "model", so the general brand+model key degrades to a bare brand
# and collapses every shirt of a brand into one template. build_apparel_signature widens the
# key and refuses to produce one at all until brand AND size are both known.

APPAREL_CASES = [
    # (brand, model, style, size, department, expected)
    ("Patagonia", None, "Button-Up", "M", "mens", "patagonia button up m mens"),
    ("patagonia", None, "button-up", "m", "mens", "patagonia button up m mens"),  # casefolded
    ("Nike", "Dri-FIT", "Polo", "L", "mens", "nike dri fit polo l mens"),
    ("Levi's", None, "Straight Jean", "32x34", "mens", "levi s straight jean 32x34 mens"),
    # Partial records still key off what's known, as long as brand+size are there.
    ("Patagonia", None, None, "M", None, "patagonia m"),
    ("Patagonia", None, "Button-Up", "M", None, "patagonia button up m"),
    # No size => no signature: nobody has read the tag, so there is nothing safe to reuse.
    ("Patagonia", None, "Button-Up", None, "mens", None),
    ("Patagonia", None, "Button-Up", "", "mens", None),
    ("Patagonia", None, "Button-Up", "   ", "mens", None),
    # No brand => no signature either.
    (None, None, "Button-Up", "M", "mens", None),
    ("", None, "Button-Up", "M", "mens", None),
    ("   ", None, "Button-Up", "M", "mens", None),
]


@pytest.mark.parametrize("brand,model,style,size,department,expected", APPAREL_CASES)
def test_build_apparel_signature(brand, model, style, size, department, expected):
    assert build_apparel_signature(brand, model, style, size, department) == expected


def test_apparel_sizes_do_not_collapse():
    """The bug the wider key exists to prevent: same style, different size => different
    template. Reusing one across sizes would post the wrong size in the item specifics."""
    medium = build_apparel_signature("Patagonia", None, "Button-Up", "M", "mens")
    large = build_apparel_signature("Patagonia", None, "Button-Up", "L", "mens")
    assert medium != large


def test_apparel_brands_do_not_collapse_across_styles():
    """Two different Nike garments in the same size must not share a template."""
    polo = build_apparel_signature("Nike", None, "Polo", "L", "mens")
    tee = build_apparel_signature("Nike", None, "Crewneck Tee", "L", "mens")
    assert polo != tee


class _Item:
    """Minimal stand-in for the ORM Item — signature_for_item only reads attributes."""

    def __init__(self, **kw):
        defaults = dict(
            item_kind="general", brand=None, model=None, style=None, size=None, department=None
        )
        defaults.update(kw)
        for key, value in defaults.items():
            setattr(self, key, value)


def test_signature_for_item_dispatches_on_kind():
    """General goods keep the narrow brand+model key; clothing gets the wide one. Both
    call sites (capture-time match, sale-time create) go through this one function."""
    lure = _Item(item_kind="general", brand="Rapala", model="F11")
    assert signature_for_item(lure) == "rapala f11"

    shirt = _Item(
        item_kind="clothing", brand="Patagonia", style="Button-Up", size="M", department="mens"
    )
    assert signature_for_item(shirt) == "patagonia button up m mens"


def test_clothing_without_size_never_matches_a_template():
    """The collapse guard, at the dispatch level: a Nike shirt whose tag was never read
    must not adopt a template built from a different Nike shirt."""
    unread = _Item(item_kind="clothing", brand="Nike", style="Polo")
    assert signature_for_item(unread) is None


def test_capture_and_sale_time_apparel_signatures_agree():
    """Same invariant as the general case: the signature is stored on the item, so the
    sale-time template key reproduces the capture-time match key exactly."""
    shirt = _Item(
        item_kind="clothing", brand="Patagonia", style="Button-Up", size="M", department="mens"
    )
    assert signature_for_item(shirt) == build_apparel_signature(
        shirt.brand, shirt.model, shirt.style, shirt.size, shirt.department
    )
