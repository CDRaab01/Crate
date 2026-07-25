"""Table-driven tests for the pure signature module (CLAUDE.md §9: matching math is
centralized, pure, and exhaustively tested)."""

import pytest

from app.matching.signature import build_signature

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
