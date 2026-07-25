"""The async draft pipeline: cleanup → identify → (Phase 3 dup-check) → (Phase 4 price).

Runs as a FastAPI background task with its own DB session — the scan endpoint returns 202
immediately and the review stack polls GET /items/{id} until processed_at is set.

House AI guardrails: vision output is schema-validated with salvage (identify_prompts);
content failures degrade to a low-confidence draft; transport failures land in scan_error.
Nothing here posts anywhere — the user reviews and approves before eBay is ever touched.
"""

import asyncio
import datetime
import logging
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.models.item import Item
from app.services import photo_store
from app.services.ai.vision import data_url, identify_item
from app.services.cleanup import clean_photo

logger = logging.getLogger(__name__)

# Identification reads at most this many photos (the first N by order) — enough angles to
# identify, small enough to keep local vision latency sane.
MAX_IDENTIFY_PHOTOS = 3


async def process_item(item_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        item = (
            await db.execute(
                select(Item).options(selectinload(Item.photos)).where(Item.id == item_id)
            )
        ).scalar_one_or_none()
        if item is None:  # deleted while queued
            return

        try:
            identify_urls: list[str] = []
            for photo in item.photos:
                original = photo_store.read_bytes(photo.original_path)
                # CPU-bound (onnx + Pillow) — keep the event loop free.
                cleaned_bytes = await asyncio.to_thread(clean_photo, original)
                cleaned_path = photo_store.cleaned_path_for(item_id, photo.order)
                await asyncio.to_thread(_write, cleaned_path, cleaned_bytes)
                photo.cleaned_path = cleaned_path
                if len(identify_urls) < MAX_IDENTIFY_PHOTOS:
                    identify_urls.append(data_url(cleaned_bytes, "image/png"))

            draft = await identify_item(identify_urls)

            item.title = draft.title
            item.description = _compose_description(draft.description, draft.condition_notes)
            item.brand = draft.brand
            item.model = draft.model
            item.condition = draft.condition
            if draft.weight_oz is not None:
                item.weight_oz_est = round(draft.weight_oz, 2)
            item.dims_in_est = draft.dims_in
            if draft.confidence == "low":
                item.scan_error = "low_confidence"
        except HTTPException as e:
            # Transport failure (LM Studio down/slow/broken): the draft survives with its
            # photos; the review stack shows why identification is missing.
            item.scan_error = f"identify_unavailable: {e.detail}"
        except Exception:
            logger.exception("scan pipeline failed for item %s", item_id)
            item.scan_error = "scan_failed"

        item.processed_at = datetime.datetime.now(datetime.timezone.utc)
        await db.commit()


def _write(path: str, data: bytes) -> None:
    from pathlib import Path

    Path(path).write_bytes(data)


def _compose_description(description: str | None, condition_notes: str | None) -> str | None:
    if description and condition_notes:
        return f"{description}\n\nCondition: {condition_notes}"
    return description or condition_notes
