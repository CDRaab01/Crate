"""Apparel round-trip through the API: the scan pipeline persists what vision read, PATCH
edits and clears the specifics, and ItemOut reports the completeness gaps.

This is the archive-first contract end to end — capture a garment with no eBay keyset
anywhere in sight, and still end up with a record that says exactly what a human must add
while the shirt is still in hand.
"""

import asyncio

import pytest

from app.config import settings
from app.services import scan_pipeline
from app.services.ai.identify_prompts import IdentifyDraft

FAKE_PNG = b"\x89PNG\r\n\x1a\nfakebytes"


@pytest.fixture(autouse=True)
def photos_tmpdir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "photos_dir", str(tmp_path / "photos"))


def _shirt_draft(**overrides) -> IdentifyDraft:
    base = {
        "title": "Patagonia Organic Cotton Button-Up Navy Mens M",
        "brand": "Patagonia",
        "model": None,
        "category_hint": "mens casual shirts",
        "condition": "good",
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
    base.update(overrides)
    return IdentifyDraft(**base)


@pytest.fixture
def shirt_pipeline(monkeypatch):
    """Vision reads a fully-tagged shirt."""

    def _install(draft: IdentifyDraft):
        monkeypatch.setattr(scan_pipeline, "clean_photo", lambda b: b + b"-cleaned")

        async def fake_identify(urls, client=None):
            return draft

        monkeypatch.setattr(scan_pipeline, "identify_item", fake_identify)

    _install(_shirt_draft())
    return _install


def _photo_files(n=2):
    return [("photos", (f"p{i}.png", FAKE_PNG, "image/png")) for i in range(n)]


async def _scan(client, attempts=50):
    r = await client.post("/items/scan", files=_photo_files())
    item_id = r.json()["id"]
    for _ in range(attempts):
        r = await client.get(f"/items/{item_id}")
        if r.json()["processed_at"] is not None:
            return r.json()
        await asyncio.sleep(0.05)
    raise AssertionError("draft never finished processing")


async def test_scan_persists_apparel_specifics(auth_client, shirt_pipeline):
    item = await _scan(auth_client)
    assert item["item_kind"] == "clothing"
    assert item["size"] == "M"
    assert item["size_type"] == "regular"
    assert item["department"] == "mens"
    assert item["color"] == "Navy"
    assert item["material"] == "100% Organic Cotton"
    assert item["style"] == "Button-Up"
    assert item["sleeve_length"] == "long"
    # Never AI-set: a vision model cannot hold a tape measure.
    assert item["measurements_in"] is None
    assert "measurements" in item["missing_hand_only"]


async def test_unread_tag_surfaces_as_hand_only_gaps(auth_client, shirt_pipeline):
    """The case this whole round exists for: photos taken, tag never captured. The record
    must say so rather than looking complete."""
    shirt_pipeline(_shirt_draft(size=None, size_type=None, material=None))
    item = await _scan(auth_client)

    assert item["size"] is None
    assert set(item["missing_hand_only"]) == {"size", "size_type", "material", "measurements"}
    for field in ("size", "size_type", "material"):
        assert field in item["missing_for_listing"]


async def test_general_goods_report_no_apparel_gaps(auth_client, shirt_pipeline):
    """A lure is not under-documented just because it has no size."""
    shirt_pipeline(
        _shirt_draft(
            item_kind="general",
            brand="Rapala",
            model="F11",
            department=None,
            size=None,
            size_type=None,
            color=None,
            material=None,
            style=None,
            fit=None,
            sleeve_length=None,
        )
    )
    item = await _scan(auth_client)
    assert item["item_kind"] == "general"
    assert item["missing_for_listing"] == []
    assert item["missing_hand_only"] == []


async def test_patch_fills_the_hand_only_gaps(auth_client, shirt_pipeline):
    """The review-stack edit that closes an archive out: type the tag, measure the garment,
    say which bin it went into."""
    shirt_pipeline(_shirt_draft(size=None, size_type=None, material=None))
    item = await _scan(auth_client)
    assert item["missing_hand_only"]

    r = await auth_client.patch(
        f"/items/{item['id']}",
        json={
            "size": "M",
            "size_type": "regular",
            "material": "100% Organic Cotton",
            "measurements_in": {"chest": 21, "length": 29, "sleeve": 24.5},
            "storage_location": "Bin 3",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["size"] == "M"
    assert body["measurements_in"] == {"chest": 21.0, "length": 29.0, "sleeve": 24.5}
    assert body["storage_location"] == "Bin 3"
    assert body["missing_hand_only"] == []
    assert body["missing_for_listing"] == []


async def test_patch_normalizes_enum_shape(auth_client, shirt_pipeline):
    item = await _scan(auth_client)
    r = await auth_client.patch(
        f"/items/{item['id']}",
        json={"size_type": "Big & Tall", "department": "Mens", "sleeve_length": "Short Sleeve"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["size_type"] == "big_tall"
    assert body["department"] == "mens"
    assert body["sleeve_length"] == "short"


async def test_patch_rejects_unknown_enum_values(auth_client, shirt_pipeline):
    """Hand edits reject rather than degrade (unlike the vision path): silently NULLing a
    value the user believes they filled in is worse than a 422."""
    item = await _scan(auth_client)
    for payload in ({"size_type": "XL"}, {"department": "toddler"}, {"item_kind": "furniture"}):
        r = await auth_client.patch(f"/items/{item['id']}", json=payload)
        assert r.status_code == 422, f"{payload} -> {r.status_code}"


async def test_patch_clears_apparel_text_and_measurements(auth_client, shirt_pipeline):
    """Suite PATCH convention: omitted = untouched, "" = clear. An all-empty measurements
    body clears the tape readings (a mis-measured garment must be correctable to "unknown")."""
    item = await _scan(auth_client)

    r = await auth_client.patch(
        f"/items/{item['id']}",
        json={"measurements_in": {"chest": 21, "length": 29}, "storage_location": "Bin 3"},
    )
    assert r.json()["measurements_in"] == {"chest": 21.0, "length": 29.0}

    r = await auth_client.patch(
        f"/items/{item['id']}",
        json={"size": "", "color": "", "storage_location": "", "measurements_in": {}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["size"] is None
    assert body["color"] is None
    assert body["storage_location"] is None
    assert body["measurements_in"] is None
    assert body["material"] == "100% Organic Cotton"  # omitted = untouched


async def test_patch_clears_apparel_enums(auth_client, shirt_pipeline):
    item = await _scan(auth_client)
    r = await auth_client.patch(
        f"/items/{item['id']}", json={"size_type": "", "department": "", "fit": ""}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["size_type"] is None
    assert body["department"] is None
    assert body["fit"] is None
    # item_kind is NOT NULL — "" must not blank it into an invalid state.
    assert body["item_kind"] == "clothing"


async def test_item_kind_survives_empty_string(auth_client, shirt_pipeline):
    item = await _scan(auth_client)
    r = await auth_client.patch(f"/items/{item['id']}", json={"item_kind": ""})
    assert r.status_code == 200, r.text
    assert r.json()["item_kind"] == "clothing"


async def test_out_of_range_measurements_rejected(auth_client, shirt_pipeline):
    """Centimetres typed into an inches field, or a stray keystroke."""
    item = await _scan(auth_client)
    for bad in ({"chest": 0}, {"chest": -3}, {"chest": 400}):
        r = await auth_client.patch(f"/items/{item['id']}", json={"measurements_in": bad})
        assert r.status_code == 422, f"{bad} -> {r.status_code}"


async def test_unknown_measurement_key_rejected(auth_client, shirt_pipeline):
    item = await _scan(auth_client)
    r = await auth_client.patch(f"/items/{item['id']}", json={"measurements_in": {"collar": 16}})
    assert r.status_code == 422


async def test_storage_location_round_trips_in_the_registry(auth_client, shirt_pipeline):
    """A registry that can't say which bin a sold shirt is in isn't usable at ship time,
    which is months away here."""
    item = await _scan(auth_client)
    await auth_client.patch(f"/items/{item['id']}", json={"storage_location": "Closet A shelf 2"})
    r = await auth_client.get("/items")
    assert r.status_code == 200
    listed = [i for i in r.json() if i["id"] == item["id"]]
    assert listed and listed[0]["storage_location"] == "Closet A shelf 2"
