"""Template reuse-on-capture (the duplicate fast-path) + the templates router."""

import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.duplicate_template import DuplicateTemplate
from app.models.user import User
from app.services import scan_pipeline
from app.services.ai.identify_prompts import IdentifyDraft

FAKE_PNG = b"\x89PNG\r\n\x1a\nfakebytes"


@pytest.fixture(autouse=True)
def photos_tmpdir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "photos_dir", str(tmp_path / "photos"))


@pytest.fixture
def identify_rapala(monkeypatch):
    monkeypatch.setattr(scan_pipeline, "clean_photo", lambda b: b)

    async def fake_identify(urls, client=None):
        return IdentifyDraft(
            title="Some vision title",
            brand="Rapala",
            model="F11",
            description="Vision description.",
            confidence="high",
        )

    monkeypatch.setattr(scan_pipeline, "identify_item", fake_identify)


async def _seed_template(client) -> DuplicateTemplate:
    """A proven listing pattern for the auth_client's user."""
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.id == client.user_id))).scalar_one()
        template = DuplicateTemplate(
            user_id=user.id,
            item_signature="rapala f11",
            title_template="Rapala Original Floater F11 — proven title",
            description_template="Proven description that sold before.",
            category_id="52149",
            use_count=3,
        )
        db.add(template)
        await db.commit()
        await db.refresh(template)
        return template


async def _wait_processed(client, item_id, attempts=50):
    for _ in range(attempts):
        r = await client.get(f"/items/{item_id}")
        if r.json()["processed_at"] is not None:
            return r.json()
        await asyncio.sleep(0.05)
    raise AssertionError("draft never finished processing")


async def test_recapture_prefills_from_template(auth_client, identify_rapala):
    template = await _seed_template(auth_client)

    r = await auth_client.post("/items/scan", files=[("photos", ("p.png", FAKE_PNG, "image/png"))])
    item = await _wait_processed(auth_client, r.json()["id"])

    # The template's proven copy wins over the fresh vision draft; the badge is template_id.
    assert item["title"] == "Rapala Original Floater F11 — proven title"
    assert item["description"] == "Proven description that sold before."
    assert item["category_id"] == "52149"
    assert item["template_id"] == str(template.id)


async def test_no_template_match_keeps_vision_draft(auth_client, identify_rapala):
    r = await auth_client.post("/items/scan", files=[("photos", ("p.png", FAKE_PNG, "image/png"))])
    item = await _wait_processed(auth_client, r.json()["id"])
    assert item["title"] == "Some vision title"
    assert item["template_id"] is None


async def test_templates_router_list_and_delete(auth_client):
    template = await _seed_template(auth_client)

    r = await auth_client.get("/templates")
    assert r.status_code == 200
    listed = r.json()
    assert [t["id"] for t in listed] == [str(template.id)]
    assert listed[0]["use_count"] == 3

    r = await auth_client.delete(f"/templates/{template.id}")
    assert r.status_code == 204
    r = await auth_client.get("/templates")
    assert r.json() == []


async def test_templates_owner_scoped(auth_client, client):
    template = await _seed_template(auth_client)

    # A different user sees nothing and can't delete it.
    async with AsyncSessionLocal() as db:
        other = User(name="O", email=f"tpl_{uuid.uuid4().hex[:8]}@crate.test")
        db.add(other)
        await db.commit()
        await db.refresh(other)
    from app.security import create_access_token

    client.headers["Authorization"] = f"Bearer {create_access_token(str(other.id))}"
    r = await client.get("/templates")
    assert r.json() == []
    r = await client.delete(f"/templates/{template.id}")
    assert r.status_code == 404
