"""Roles on the wire, and the routing they buy: the label pass must see the TAG photo.

The whole point of roles is that the second pass is pointed at the label rather than
guessing, so the sharpest available test is asserting which data URLs each pass received —
the same trick test_photo_pipeline.py's real_vision fixture uses to prove identification
gets real cleaned PNGs. Cleanup and both vision calls are stubbed; CI never touches rembg
or LM Studio.

Note the fixtures carry no legible text, so these tests prove ROUTING and never OCR
accuracy. Whether the model can actually read a tag is measured against real photographs
with scripts/photo_smoke.py.
"""

import asyncio
import base64

import pytest

from app.config import settings
from app.services import scan_pipeline
from app.services.ai.identify_prompts import IdentifyDraft
from app.services.ai.label_prompts import LabelDraft

FAKE_PNG = b"\x89PNG\r\n\x1a\nfakebytes"


@pytest.fixture(autouse=True)
def photos_tmpdir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "photos_dir", str(tmp_path / "photos"))


@pytest.fixture
def recording_pipeline(monkeypatch):
    """Stub both AI passes and record exactly which images each one was handed."""
    seen: dict[str, list[str]] = {"identify": [], "label": []}
    # Distinct bytes per photo so a data URL can be traced back to the photo it came from.
    monkeypatch.setattr(scan_pipeline, "clean_photo", lambda b: b + b"-cleaned")

    async def fake_identify(urls, client=None):
        seen["identify"] = list(urls)
        return IdentifyDraft(
            title="Navy button-up",
            description="A shirt.",
            item_kind="clothing",
            confidence="high",
        )

    async def fake_read_label(urls, client=None):
        seen["label"] = list(urls)
        return LabelDraft(size="M", material="100% Cotton")

    monkeypatch.setattr(scan_pipeline, "identify_item", fake_identify)
    monkeypatch.setattr(scan_pipeline, "read_label", fake_read_label)
    return seen


def _files(*roles):
    """One distinguishable PNG per photo, plus the parallel roles field."""
    files = [("photos", (f"p{i}.png", FAKE_PNG + bytes([i]), "image/png")) for i in range(len(roles))]
    files += [("roles", (None, role)) for role in roles if role is not None]
    return files


async def _wait_processed(client, item_id, attempts=50):
    for _ in range(attempts):
        r = await client.get(f"/items/{item_id}")
        if r.json()["processed_at"] is not None:
            return r.json()
        await asyncio.sleep(0.05)
    raise AssertionError("draft never finished processing")


# ── the wire contract ─────────────────────────────────────────────────────────────────


async def test_roles_are_stored_per_photo(auth_client, recording_pipeline):
    r = await auth_client.post("/items/scan", files=_files("front", "back", "tag"))
    assert r.status_code == 202
    item = await _wait_processed(auth_client, r.json()["id"])
    by_order = {p["order"]: p["role"] for p in item["photos"]}
    assert by_order == {0: "front", 1: "back", 2: "tag"}


async def test_roles_are_optional(auth_client, recording_pipeline):
    """Every pre-guided-capture client — including the deploy smoke — sends none."""
    r = await auth_client.post(
        "/items/scan", files=[("photos", ("p0.png", FAKE_PNG, "image/png"))]
    )
    assert r.status_code == 202
    item = await _wait_processed(auth_client, r.json()["id"])
    assert [p["role"] for p in item["photos"]] == [None]


async def test_role_count_must_match_photo_count(auth_client, recording_pipeline):
    """Zipping a short list would silently attach roles to the wrong photos."""
    files = [("photos", (f"p{i}.png", FAKE_PNG, "image/png")) for i in range(3)]
    files += [("roles", (None, "front")), ("roles", (None, "tag"))]
    r = await auth_client.post("/items/scan", files=files)
    assert r.status_code == 422
    assert "one role per photo" in r.json()["detail"]


async def test_unknown_role_is_rejected_not_degraded(auth_client, recording_pipeline):
    """A role is a value OUR client chose — unlike vision output, a bad one is a bug."""
    r = await auth_client.post("/items/scan", files=_files("front", "hero"))
    assert r.status_code == 422
    assert "hero" in r.json()["detail"]


async def test_role_casing_is_forgiving(auth_client, recording_pipeline):
    r = await auth_client.post("/items/scan", files=_files("Front", "  TAG  "))
    assert r.status_code == 202
    item = await _wait_processed(auth_client, r.json()["id"])
    assert [p["role"] for p in item["photos"]] == ["front", "tag"]


# ── the routing that roles buy ────────────────────────────────────────────────────────


async def test_label_pass_receives_only_the_tag_photo(auth_client, recording_pipeline):
    r = await auth_client.post("/items/scan", files=_files("front", "back", "tag"))
    await _wait_processed(auth_client, r.json()["id"])

    assert len(recording_pipeline["label"]) == 1, "the label pass should see exactly the tag"
    tag_url = recording_pipeline["label"][0]
    assert tag_url.startswith("data:image/png;base64,")
    # And identification should NOT have been handed the tag close-up.
    assert tag_url not in recording_pipeline["identify"]
    assert len(recording_pipeline["identify"]) == 2

    # The label pass reads the ORIGINAL bytes, not the cleaned copy — measured 15/18 vs
    # 10/18 sizes read, and cleanup is built for garments on backgrounds, not flat labels.
    # The stub marks cleaned output with a suffix, so this distinguishes the two.
    decoded = base64.b64decode(tag_url.split(",", 1)[1])
    assert b"-cleaned" not in decoded, "the label pass must see the original, not the cleanup"
    for url in recording_pipeline["identify"]:
        assert b"-cleaned" in base64.b64decode(url.split(",", 1)[1]), (
            "identification still reads cleaned photos"
        )


async def test_tag_photo_beyond_the_identify_budget_still_reaches_the_label_pass(
    auth_client, recording_pipeline
):
    """The concrete bug roles fix: MAX_IDENTIFY_PHOTOS is 3 and reads by order, so a tag
    shot fourth used to never reach any model at all."""
    r = await auth_client.post("/items/scan", files=_files("front", "back", "detail", "tag"))
    await _wait_processed(auth_client, r.json()["id"])
    assert len(recording_pipeline["label"]) == 1
    assert len(recording_pipeline["identify"]) == scan_pipeline.MAX_IDENTIFY_PHOTOS


async def test_no_tag_photo_means_no_label_call(auth_client, recording_pipeline):
    """No point spending a vision round trip when there is no label to read."""
    r = await auth_client.post("/items/scan", files=_files("front", "back"))
    item = await _wait_processed(auth_client, r.json()["id"])
    assert recording_pipeline["label"] == []
    assert item["missing_photo_roles"] == ["tag_photo"]


async def test_tag_photo_clears_the_archive_gap(auth_client, recording_pipeline):
    r = await auth_client.post("/items/scan", files=_files("front", "tag"))
    item = await _wait_processed(auth_client, r.json()["id"])
    assert item["missing_photo_roles"] == []


async def test_roleless_item_falls_back_to_current_behaviour(auth_client, recording_pipeline):
    """Old clients: identification still gets the first N photos, no label pass fires."""
    files = [("photos", (f"p{i}.png", FAKE_PNG + bytes([i]), "image/png")) for i in range(4)]
    r = await auth_client.post("/items/scan", files=files)
    await _wait_processed(auth_client, r.json()["id"])
    assert len(recording_pipeline["identify"]) == scan_pipeline.MAX_IDENTIFY_PHOTOS
    assert recording_pipeline["label"] == []


# ── the merge and its failure mode ────────────────────────────────────────────────────


async def test_label_fills_size_that_identification_left_blank(auth_client, recording_pipeline):
    r = await auth_client.post("/items/scan", files=_files("front", "tag"))
    item = await _wait_processed(auth_client, r.json()["id"])
    assert item["size"] == "M"
    assert item["material"] == "100% Cotton"
    # …and the gap list no longer nags for them.
    assert "size" not in item["missing_hand_only"]


async def test_label_never_overwrites_what_identification_read(auth_client, monkeypatch):
    """Identification saw the whole garment; where the two disagree, the first read wins."""
    monkeypatch.setattr(scan_pipeline, "clean_photo", lambda b: b + b"-cleaned")

    async def fake_identify(urls, client=None):
        return IdentifyDraft(
            title="Shirt", description="A shirt.", item_kind="clothing", size="L",
            material="Linen", confidence="high",
        )

    async def fake_read_label(urls, client=None):
        return LabelDraft(size="M", material="100% Cotton", size_type="petite")

    monkeypatch.setattr(scan_pipeline, "identify_item", fake_identify)
    monkeypatch.setattr(scan_pipeline, "read_label", fake_read_label)

    r = await auth_client.post("/items/scan", files=_files("front", "tag"))
    item = await _wait_processed(auth_client, r.json()["id"])
    assert item["size"] == "L", "identification's read must win"
    assert item["material"] == "Linen"
    # …but a field it left blank is still filled.
    assert item["size_type"] == "petite"


async def test_a_failing_label_pass_does_not_poison_a_good_identify(auth_client, monkeypatch):
    """The trap this feature had to design around. If the label call's HTTPException reached
    the outer handler, a perfectly good identification would be reported as
    identify_unavailable and template matching + pricing would be skipped."""
    from fastapi import HTTPException
    from fastapi import status as http_status

    monkeypatch.setattr(scan_pipeline, "clean_photo", lambda b: b + b"-cleaned")

    async def fake_identify(urls, client=None):
        return IdentifyDraft(
            title="Navy button-up", description="A shirt.", item_kind="clothing",
            brand="Orvis", confidence="high",
        )

    async def dead_label(urls, client=None):
        raise HTTPException(
            http_status.HTTP_503_SERVICE_UNAVAILABLE, "Couldn't reach LM Studio. Is it running?"
        )

    monkeypatch.setattr(scan_pipeline, "identify_item", fake_identify)
    monkeypatch.setattr(scan_pipeline, "read_label", dead_label)

    r = await auth_client.post("/items/scan", files=_files("front", "tag"))
    item = await _wait_processed(auth_client, r.json()["id"])

    assert item["scan_error"] is None, "a label outage must not look like an identify outage"
    assert item["title"] == "Navy button-up", "identification's work must survive"
    assert item["brand"] == "Orvis"
    assert item["size"] is None, "and the gap is simply left for a human"
    assert "size" in item["missing_hand_only"]
