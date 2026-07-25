"""Scan endpoint + pipeline tests: cleanup and vision are mocked (CI never touches rembg or
LM Studio); the pipeline's state reporting (processed_at / scan_error) is the contract the
review stack polls on."""

import asyncio
import uuid

import pytest
from fastapi import HTTPException, status

from app.config import settings
from app.services import scan_pipeline
from app.services.ai.identify_prompts import IdentifyDraft

FAKE_PNG = b"\x89PNG\r\n\x1a\nfakebytes"


@pytest.fixture(autouse=True)
def photos_tmpdir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "photos_dir", str(tmp_path / "photos"))


@pytest.fixture
def pipeline_mocked(monkeypatch):
    """Deterministic pipeline: cleanup is a passthrough, identify returns a rich draft."""
    monkeypatch.setattr(scan_pipeline, "clean_photo", lambda b: b + b"-cleaned")

    async def fake_identify(urls, client=None):
        return IdentifyDraft(
            title="Rapala Original Floater F11",
            brand="Rapala",
            model="F11",
            category_hint="fishing lures",
            condition="good",
            condition_notes="light hook rash",
            description="A classic balsa minnow.",
            weight_oz=3.5,
            dims_in={"l": 6, "w": 3, "h": 2},
            confidence="high",
        )

    monkeypatch.setattr(scan_pipeline, "identify_item", fake_identify)


def _photo_files(n=2):
    return [("photos", (f"p{i}.png", FAKE_PNG, "image/png")) for i in range(n)]


async def _wait_processed(client, item_id, attempts=50):
    for _ in range(attempts):
        r = await client.get(f"/items/{item_id}")
        if r.json()["processed_at"] is not None:
            return r.json()
        await asyncio.sleep(0.05)
    raise AssertionError("draft never finished processing")


async def test_scan_creates_processed_draft(auth_client, pipeline_mocked):
    r = await auth_client.post("/items/scan", files=_photo_files())
    assert r.status_code == status.HTTP_202_ACCEPTED, r.text
    body = r.json()
    assert body["status"] == "draft" and body["photo_count"] == 2

    item = await _wait_processed(auth_client, body["id"])
    assert item["title"] == "Rapala Original Floater F11"
    assert item["brand"] == "Rapala"
    assert item["condition"] == "good"
    assert "Condition: light hook rash" in item["description"]
    assert item["weight_oz_est"] == "3.50"
    assert item["dims_in_est"] == {"l": 6, "w": 3, "h": 2}
    assert item["scan_error"] is None
    assert [p["cleaned"] for p in item["photos"]] == [True, True]


async def test_scan_survives_lm_studio_down(auth_client, monkeypatch):
    monkeypatch.setattr(scan_pipeline, "clean_photo", lambda b: b)

    async def dead_identify(urls, client=None):
        raise HTTPException(503, "Couldn't reach LM Studio. Is it running?")

    monkeypatch.setattr(scan_pipeline, "identify_item", dead_identify)

    r = await auth_client.post("/items/scan", files=_photo_files(1))
    item = await _wait_processed(auth_client, r.json()["id"])
    # The draft survives with photos; the error is honest and visible.
    assert item["title"] is None
    assert item["scan_error"].startswith("identify_unavailable")
    assert [p["cleaned"] for p in item["photos"]] == [True]


async def test_scan_low_confidence_flagged(auth_client, monkeypatch):
    monkeypatch.setattr(scan_pipeline, "clean_photo", lambda b: b)

    async def vague_identify(urls, client=None):
        return IdentifyDraft(title="Unknown item", confidence="low")

    monkeypatch.setattr(scan_pipeline, "identify_item", vague_identify)

    r = await auth_client.post("/items/scan", files=_photo_files(1))
    item = await _wait_processed(auth_client, r.json()["id"])
    assert item["scan_error"] == "low_confidence"


async def test_scan_rejects_wrong_type_and_counts(auth_client):
    r = await auth_client.post("/items/scan", files=[("photos", ("a.gif", b"x", "image/gif"))])
    assert r.status_code == 422
    r = await auth_client.post("/items/scan", files=_photo_files(9))
    assert r.status_code == 422


async def test_scan_requires_auth(client):
    r = await client.post("/items/scan", files=_photo_files(1))
    assert r.status_code == 401


async def test_patch_review_edits_and_clearing(auth_client, pipeline_mocked):
    r = await auth_client.post("/items/scan", files=_photo_files(1))
    item = await _wait_processed(auth_client, r.json()["id"])

    r = await auth_client.patch(
        f"/items/{item['id']}",
        json={"title": "Rapala F11 Silver — excellent", "brand": "", "condition": "like_new"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "Rapala F11 Silver — excellent"
    assert body["brand"] is None  # "" clears (suite PATCH convention)
    assert body["model"] == "F11"  # omitted = untouched
    assert body["condition"] == "like_new"

    r = await auth_client.patch(f"/items/{item['id']}", json={"condition": "mint"})
    assert r.status_code == 422


async def test_items_are_owner_scoped(auth_client, client, pipeline_mocked):
    r = await auth_client.post("/items/scan", files=_photo_files(1))
    item_id = r.json()["id"]
    await _wait_processed(auth_client, item_id)

    # A second user can't see or edit it.
    other = await _fresh_auth(client)
    r = await other.get(f"/items/{item_id}")
    assert r.status_code == 404
    r = await other.patch(f"/items/{item_id}", json={"title": "mine now"})
    assert r.status_code == 404


async def test_delete_draft_only(auth_client, pipeline_mocked):
    r = await auth_client.post("/items/scan", files=_photo_files(1))
    item_id = r.json()["id"]
    await _wait_processed(auth_client, item_id)
    r = await auth_client.delete(f"/items/{item_id}")
    assert r.status_code == 204
    r = await auth_client.get(f"/items/{item_id}")
    assert r.status_code == 404


async def _fresh_auth(client):
    from app.database import AsyncSessionLocal
    from app.models.user import User
    from app.security import create_access_token

    async with AsyncSessionLocal() as db:
        user = User(name="Other", email=f"other_{uuid.uuid4().hex[:8]}@crate.test")
        db.add(user)
        await db.commit()
        await db.refresh(user)
    client.headers["Authorization"] = f"Bearer {create_access_token(str(user.id))}"
    return client
