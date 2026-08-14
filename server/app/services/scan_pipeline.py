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
from app.matching.signature import signature_for_item
from app.models.duplicate_template import DuplicateTemplate
from app.models.item import Item
from app.pricing.service import price_item
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

            # Apparel specifics: whatever the tag actually showed. Nulls are meaningful here
            # — they are what missing_hand_only reports, i.e. "go read the tag before this
            # goes in a bin". measurements_in is never AI-set; a tape measure is human work.
            item.item_kind = draft.item_kind
            item.department = draft.department
            item.size = draft.size
            item.size_type = draft.size_type
            item.color = draft.color
            item.material = draft.material
            item.style = draft.style
            item.fit = draft.fit
            item.sleeve_length = draft.sleeve_length

            if draft.confidence == "low":
                item.scan_error = "low_confidence"

            # Duplicate fast-path: a matching template (the same thing sold before — see
            # signature_for_item, which keys clothing on brand+style+size) wins
            # the sellable copy — identification ran only to confirm the match. The client
            # badges template_id != null as "from template — previously sold N times".
            signature = signature_for_item(item)
            if signature is not None:
                template = (
                    await db.execute(
                        select(DuplicateTemplate).where(
                            DuplicateTemplate.user_id == item.user_id,
                            DuplicateTemplate.item_signature == signature,
                        )
                    )
                ).scalar_one_or_none()
                if template is not None:
                    item.title = template.title_template
                    if template.description_template:
                        item.description = template.description_template
                    item.category_id = template.category_id or item.category_id
                    item.template_id = template.id

            # Price research (Phase 4): active comps → quick/patient. Best-effort — an
            # unconfigured keyset or eBay outage means a draft without prices, never a
            # dead draft (the review UI says so and the user can type a price).
            await price_item(item)
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
