"""The narrow care-label read: parser salvage, and the guardrails that must stay in the prompt.

Mirrors test_identify_prompts.py deliberately — same table-driven shape, same salvage cases,
and the same kind of literal prompt-text assertion. That last one matters more here than
anywhere: this prompt exists BECAUSE a previous attempt to make the omnibus prompt read
sizes harder produced a confident wrong answer, so a silent edit softening the never-infer
rule would reintroduce exactly the failure this module was written to avoid.
"""

import json

import pytest

from app.services.ai.label_prompts import (
    LABEL_SYSTEM_PROMPT,
    LABEL_USER_PROMPT,
    build_label_messages,
    parse_label,
)

GOOD = {"size": "M", "size_type": "regular", "material": "100% Cotton"}


def test_parses_a_clean_reply():
    draft = parse_label(json.dumps(GOOD))
    assert draft is not None
    assert (draft.size, draft.size_type, draft.material) == ("M", "regular", "100% Cotton")


def test_salvages_a_fenced_reply():
    draft = parse_label("```json\n" + json.dumps(GOOD) + "\n```")
    assert draft is not None and draft.size == "M"


def test_salvages_a_prose_wrapped_reply():
    draft = parse_label("Sure! Here's the label:\n" + json.dumps(GOOD) + "\nHope that helps.")
    assert draft is not None and draft.size == "M"


@pytest.mark.parametrize(
    "raw",
    ["", "{}", "not json at all", "[]", "null", "```\n```", '{"size": null}'],
)
def test_unusable_replies_return_none(raw):
    """None means "leave whatever identification found alone" — never an empty overwrite."""
    assert parse_label(raw) is None


def test_all_null_draft_is_none_not_an_empty_draft():
    """A label with nothing readable must be indistinguishable from not having asked."""
    assert parse_label(json.dumps({"size": None, "size_type": None, "material": None})) is None


@pytest.mark.parametrize(
    "raw_size,expected",
    [
        ("X-LARGE", "X-LARGE"),
        ("32x34", "32x34"),
        ("10.5", "10.5"),
        ("中", "中"),  # non-Latin sizes are transcribed, not translated
        ("  M  ", "M"),
        ("", None),
    ],
)
def test_size_is_transcribed_verbatim(raw_size, expected):
    draft = parse_label(json.dumps({**GOOD, "size": raw_size}))
    if expected is None:
        # size blank but the other fields survive, so the draft still exists
        assert draft is not None and draft.size is None
    else:
        assert draft is not None and draft.size == expected


def test_unknown_size_type_is_dropped_not_rejected():
    """Same degrade-don't-die contract as parse_identify: the model's other fields survive."""
    draft = parse_label(json.dumps({**GOOD, "size_type": "athletic-cut"}))
    assert draft is not None
    assert draft.size_type is None
    assert draft.size == "M"


def test_size_type_normalizes_forgiving_shapes():
    draft = parse_label(json.dumps({**GOOD, "size_type": "Big & Tall"}))
    assert draft is not None and draft.size_type == "big_tall"


def test_free_text_is_length_capped_to_the_columns():
    draft = parse_label(json.dumps({"size": "S" * 100, "material": "C" * 300}))
    assert draft is not None
    assert len(draft.size) == 32  # models/item.py: size String(32)
    assert len(draft.material) == 96  # material String(96)


def test_messages_carry_every_image():
    urls = ["data:image/png;base64,AAA", "data:image/png;base64,BBB"]
    messages = build_label_messages(urls)
    assert messages[0]["role"] == "system"
    sent = [
        part["image_url"]["url"] for part in messages[1]["content"] if part["type"] == "image_url"
    ]
    assert sent == urls


def test_prompt_keeps_the_never_infer_guardrails():
    """These strings are load-bearing. Dropping one silently reintroduces guessed sizes —
    the failure that measured 3-runs-out-of-3 wrong on a circled size run."""
    assert "NEVER infer a garment's size" in LABEL_USER_PROMPT
    assert "a wrong size is a returned item" in LABEL_USER_PROMPT.lower()
    # The circled-size-run rule, and the refusal to pick when nothing is marked.
    assert "circled" in LABEL_USER_PROMPT
    assert "set size to null" in LABEL_USER_PROMPT
    # Transcription, not interpretation — the whole premise of the narrow pass.
    assert "Transcribe, do not interpret" in LABEL_USER_PROMPT
    assert "JSON" in LABEL_SYSTEM_PROMPT


def test_prompt_does_not_ask_for_measurements_or_identification():
    """Scope creep here would recreate the omnibus prompt's attention problem."""
    lowered = LABEL_USER_PROMPT.lower()
    assert "measurement" not in lowered
    assert "title" not in lowered
    assert "condition" not in lowered
