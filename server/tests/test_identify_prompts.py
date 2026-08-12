"""Table-driven tests for the identify parser — the salvage layer that keeps flaky vision
output from erroring the pipeline (suite precedent: Cookbook's photo/pantry parsers)."""

import json

import pytest

from app.services.ai.identify_prompts import build_identify_messages, parse_identify

GOOD = {
    "title": "Rapala Original Floater F11 Fishing Lure Silver",
    "brand": "Rapala",
    "model": "F11",
    "category_hint": "fishing lures",
    "condition": "good",
    "condition_notes": "Light hook rash on the belly",
    "description": "A classic balsa minnow in silver.",
    "weight_oz": 3.5,
    "dims_in": {"l": 6, "w": 3, "h": 2},
    "confidence": "high",
}


def test_clean_json_parses():
    draft = parse_identify(json.dumps(GOOD))
    assert draft is not None
    assert draft.title.startswith("Rapala")
    assert draft.brand == "Rapala"
    assert draft.condition == "good"
    assert draft.weight_oz == 3.5
    assert draft.dims_in == {"l": 6.0, "w": 3.0, "h": 2.0}
    assert draft.confidence == "high"


def test_fenced_json_is_salvaged():
    draft = parse_identify(f"```json\n{json.dumps(GOOD)}\n```")
    assert draft is not None and draft.brand == "Rapala"


def test_prose_wrapped_json_is_salvaged():
    draft = parse_identify(f"Sure! Here is the listing:\n{json.dumps(GOOD)}\nHope that helps!")
    assert draft is not None and draft.model == "F11"


@pytest.mark.parametrize(
    "raw",
    ["", "{}", "not json at all", "[]", "null", "```\n```"],
)
def test_unusable_output_returns_none(raw):
    assert parse_identify(raw) is None


def test_condition_normalized_and_validated():
    draft = parse_identify(json.dumps({**GOOD, "condition": "Like New"}))
    assert draft.condition == "like_new"
    draft = parse_identify(json.dumps({**GOOD, "condition": "mint"}))
    assert draft.condition is None  # not in the enum → dropped, not invented


def test_out_of_bounds_weight_dropped():
    draft = parse_identify(json.dumps({**GOOD, "weight_oz": 99999}))
    assert draft.weight_oz is None
    draft = parse_identify(json.dumps({**GOOD, "weight_oz": -2}))
    assert draft.weight_oz is None


def test_partial_dims_dropped():
    draft = parse_identify(json.dumps({**GOOD, "dims_in": {"l": 6, "w": 3}}))
    assert draft.dims_in is None


def test_title_clamped_to_ebay_cap():
    draft = parse_identify(json.dumps({**GOOD, "title": "x" * 200}))
    assert len(draft.title) == 80


def test_unknown_confidence_degrades_to_low():
    draft = parse_identify(json.dumps({**GOOD, "confidence": "certain"}))
    assert draft.confidence == "low"


def test_string_numbers_coerced():
    draft = parse_identify(json.dumps({**GOOD, "weight_oz": "3.5"}))
    assert draft.weight_oz == 3.5


def test_messages_carry_all_images():
    messages = build_identify_messages(["data:image/png;base64,AAA", "data:image/png;base64,BBB"])
    assert messages[0]["role"] == "system"
    images = [part for part in messages[1]["content"] if part["type"] == "image_url"]
    assert len(images) == 2


# --- Apparel block ----------------------------------------------------------------------

SHIRT = {
    "title": "Patagonia Organic Cotton Button-Up Shirt Navy Mens Medium",
    "brand": "Patagonia",
    "model": None,
    "category_hint": "mens casual shirts",
    "condition": "good",
    "condition_notes": "Slight fading at the collar",
    "description": "A navy organic-cotton button-up.",
    "weight_oz": 9.0,
    "dims_in": {"l": 12, "w": 10, "h": 2},
    "item_kind": "clothing",
    "department": "mens",
    "size": "M",
    "size_type": "regular",
    "color": "Navy",
    "material": "100% Organic Cotton",
    "style": "Button-Up",
    "fit": "regular",
    "sleeve_length": "long",
    "confidence": "high",
}


def test_apparel_block_parses():
    draft = parse_identify(json.dumps(SHIRT))
    assert draft is not None
    assert draft.item_kind == "clothing"
    assert draft.department == "mens"
    assert draft.size == "M"
    assert draft.size_type == "regular"
    assert draft.color == "Navy"
    assert draft.material == "100% Organic Cotton"
    assert draft.style == "Button-Up"
    assert draft.sleeve_length == "long"


def test_apparel_enums_are_normalized_not_rejected():
    """Vision output drifts in shape ("Mens", "Big & Tall", "Long Sleeve"); the parser
    normalizes rather than dropping otherwise-good tag data."""
    draft = parse_identify(
        json.dumps(
            {
                **SHIRT,
                "department": "Mens",
                "size_type": "Big & Tall",
                "sleeve_length": "Long Sleeve",
                "fit": "Loose",
            }
        )
    )
    assert draft is not None
    assert draft.department == "mens"
    assert draft.size_type == "big_tall"
    assert draft.sleeve_length == "long"
    assert draft.fit == "relaxed"


def test_unrecognized_apparel_enums_degrade_to_null():
    """Degrade, don't die — the same contract as the rest of this parser. A dropped enum
    resurfaces as a completeness gap rather than as junk stored on the item."""
    draft = parse_identify(
        json.dumps(
            {
                **SHIRT,
                "department": "toddler-ish",
                "size_type": "XL",
                "sleeve_length": "medium-ish",
                "fit": "???",
            }
        )
    )
    assert draft is not None
    assert draft.department is None
    assert draft.size_type is None
    assert draft.sleeve_length is None
    assert draft.fit is None
    assert draft.size == "M"  # free-text tag data is untouched by enum failures


def test_missing_apparel_block_is_exactly_pre_apparel_behaviour():
    """A model that ignores the clothing instructions entirely (or a general good) yields
    item_kind='general' and null apparel fields — no regression for the lure path."""
    draft = parse_identify(json.dumps(GOOD))
    assert draft is not None
    assert draft.item_kind == "general"
    assert draft.size is None
    assert draft.department is None
    assert draft.material is None


def test_unreadable_tag_leaves_size_null_rather_than_guessing():
    """The rule the prompt states and the archive depends on: no legible tag => null, so
    completeness can tell the user to go read it while the garment is in hand."""
    draft = parse_identify(json.dumps({**SHIRT, "size": None, "size_type": None, "material": None}))
    assert draft is not None
    assert draft.item_kind == "clothing"
    assert draft.size is None
    assert draft.material is None


def test_apparel_free_text_is_length_capped():
    draft = parse_identify(json.dumps({**SHIRT, "material": "cotton " * 100}))
    assert draft is not None and len(draft.material) <= 96


def test_prompt_forbids_guessing_size_and_measurements():
    """The guardrail lives in the prompt text, so assert it is actually there — a silent
    edit dropping it would reintroduce hallucinated sizes."""
    messages = build_identify_messages(["data:image/png;base64,AAAA"])
    prompt = messages[1]["content"][0]["text"]
    assert "NEVER infer a garment's size" in prompt
    assert "Never estimate measurements" in prompt
    assert '"item_kind"' in prompt
