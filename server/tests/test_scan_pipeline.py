"""Pure helpers in the scan pipeline — no DB, no network, no model.

`_compose_description` earns its own tests because its output is buyer-facing text on a live
listing, and the failure mode is silent: a placeholder from the vision model reads as a real
answer and ships verbatim.
"""

import pytest

from app.services import scan_pipeline


@pytest.mark.parametrize("notes", ["N/A", "n/a", " NA ", "none", "Unknown", "-", "null", "N/A."])
def test_placeholder_condition_notes_never_reach_the_description(notes):
    """The first real listing shipped with the line "Condition: N/A" visible to buyers."""
    composed = scan_pipeline._compose_description("A navy polo.", notes)
    assert composed == "A navy polo."
    assert "Condition:" not in composed


def test_real_condition_notes_are_still_appended():
    composed = scan_pipeline._compose_description("A navy polo.", "Small stain on the cuff.")
    assert composed == "A navy polo.\n\nCondition: Small stain on the cuff."


def test_condition_notes_alone_still_become_the_description():
    assert scan_pipeline._compose_description(None, "Small stain.") == "Small stain."


def test_placeholder_notes_with_no_description_leave_nothing_behind():
    assert scan_pipeline._compose_description(None, "N/A") is None
