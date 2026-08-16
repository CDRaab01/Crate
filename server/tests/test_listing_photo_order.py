"""Which photo becomes the listing's gallery image.

eBay uses the FIRST uploaded photo as the listing's main picture, and item.photos comes back
in shoot order — so before roles, whatever you happened to photograph first led the listing.
Guided capture would have made that worse, not better: prompting for a tag shot means people
will sometimes take it first.

This is the one part of the roles feature CI can verify end to end, because eBay is always
mocked at the transport (CLAUDE.md §8) — the EPS upload order is fully observable here.
"""

import uuid

import httpx
import pytest

from app.database import AsyncSessionLocal
from app.models.item import Item, ItemPhoto
from app.services.ebay import sell


class EpsRecorder:
    """Records the image bytes handed to eBay Picture Services, in upload order."""

    def __init__(self):
        self.uploaded: list[bytes] = []

    def client(self) -> httpx.AsyncClient:
        def handler(request: httpx.Request) -> httpx.Response:
            # The EPS call is multipart; the photo bytes are the part we care about.
            body = request.content
            self.uploaded.append(body)
            index = len(self.uploaded)
            return httpx.Response(
                200,
                text=f"<FullURL>https://eps.example/{index}.jpg</FullURL>",
            )

        return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _seed_item_with_photos(user_id, tmp_path, roles) -> tuple[uuid.UUID, dict]:
    """One item, one photo per role, each with distinguishable bytes."""
    marker_by_role = {}
    async with AsyncSessionLocal() as db:
        item = Item(user_id=user_id, title="Shirt", status="draft")
        db.add(item)
        await db.flush()
        for order, role in enumerate(roles):
            marker = f"PHOTO-{role or 'none'}-{order}".encode()
            path = tmp_path / f"orig_{order}.png"
            path.write_bytes(marker)
            marker_by_role[order] = marker
            db.add(ItemPhoto(item_id=item.id, order=order, role=role, original_path=str(path)))
        await db.commit()
        return item.id, marker_by_role


async def _upload_order(item_id, recorder) -> list[bytes]:
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        item = (
            await db.execute(
                select(Item).options(selectinload(Item.photos)).where(Item.id == item_id)
            )
        ).scalar_one()
        async with recorder.client() as client:
            await sell.upload_photos_to_eps(item, "token", client)
    return recorder.uploaded


@pytest.mark.parametrize(
    "shot_order,expected_first",
    [
        # The bug: tag shot first used to lead the listing.
        (["tag", "front", "back"], "front"),
        (["back", "tag", "front"], "front"),
        (["detail", "tag"], "detail"),
        # Already correct stays correct.
        (["front", "back", "tag"], "front"),
    ],
)
async def test_hero_image_is_never_the_tag(auth_client, tmp_path, shot_order, expected_first):
    item_id, markers = await _seed_item_with_photos(auth_client.user_id, tmp_path, shot_order)
    recorder = EpsRecorder()
    uploaded = await _upload_order(item_id, recorder)

    assert len(uploaded) == len(shot_order)
    first_role = shot_order[[m in uploaded[0] for m in markers.values()].index(True)]
    assert first_role == expected_first


async def test_full_order_is_front_back_detail_unknown_tag(auth_client, tmp_path):
    shot_order = ["tag", None, "detail", "back", "front"]
    item_id, markers = await _seed_item_with_photos(auth_client.user_id, tmp_path, shot_order)
    recorder = EpsRecorder()
    uploaded = await _upload_order(item_id, recorder)

    def role_of(blob: bytes) -> str:
        for order, marker in markers.items():
            if marker in blob:
                return shot_order[order] or "none"
        raise AssertionError("unrecognised upload")

    assert [role_of(b) for b in uploaded] == ["front", "back", "detail", "none", "tag"]


async def test_tag_is_included_not_dropped(auth_client, tmp_path):
    """A care label is real size proof — it goes last, it does not disappear."""
    item_id, _ = await _seed_item_with_photos(auth_client.user_id, tmp_path, ["front", "tag"])
    recorder = EpsRecorder()
    uploaded = await _upload_order(item_id, recorder)
    assert len(uploaded) == 2


async def test_roleless_item_keeps_its_original_order(auth_client, tmp_path):
    """Backward compatibility: an item captured before roles uploads exactly as it did."""
    shot_order = [None, None, None]
    item_id, markers = await _seed_item_with_photos(auth_client.user_id, tmp_path, shot_order)
    recorder = EpsRecorder()
    uploaded = await _upload_order(item_id, recorder)

    order_seen = [next(o for o, m in markers.items() if m in blob) for blob in uploaded]
    assert order_seen == [0, 1, 2]


async def test_photo_order_column_is_never_rewritten(auth_client, tmp_path):
    """Sorting is presentation-only. photo_store derives on-disk filenames from `order`, so
    renumbering to match listing order would orphan every file."""
    shot_order = ["tag", "front"]
    item_id, _ = await _seed_item_with_photos(auth_client.user_id, tmp_path, shot_order)
    recorder = EpsRecorder()
    await _upload_order(item_id, recorder)

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        item = (
            await db.execute(
                select(Item).options(selectinload(Item.photos)).where(Item.id == item_id)
            )
        ).scalar_one()
        by_role = {p.role: p.order for p in item.photos}
    assert by_role == {"tag": 0, "front": 1}, "shoot order must survive untouched"
