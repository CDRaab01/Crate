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
