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
from app.services.ai.vision import data_url, identify_item, read_label
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
            # Two collections from one cleanup pass: the photos identification will look at,
            # and the label shots the second pass will. Both are gathered here because the
            # cleaned bytes are already in hand — re-reading them off disk afterwards would
            # be pure waste.
            identify_candidates: list[tuple[str | None, str]] = []
            label_urls: list[str] = []
            for photo in item.photos:
                original = photo_store.read_bytes(photo.original_path)
                # CPU-bound (onnx + Pillow) — keep the event loop free.
                cleaned_bytes = await asyncio.to_thread(clean_photo, original)
                cleaned_path = photo_store.cleaned_path_for(item_id, photo.order)
                await asyncio.to_thread(_write, cleaned_path, cleaned_bytes)
                photo.cleaned_path = cleaned_path
                identify_candidates.append((photo.role, data_url(cleaned_bytes, "image/png")))
                if photo.role == "tag":
                    # The label pass reads the ORIGINAL, not the cleaned copy. Measured over
                    # three runs against eight real tag photographs: 15/18 sizes read from
                    # originals vs 10/18 from cleaned. Cleanup is
                    # built for garments on backgrounds and behaves unpredictably on a flat
                    # label — on one shirt it decided a woven brand tab was "the subject" and
                    # cropped the rest of the garment away. For a document-like photo the
                    # bytes the user actually took are the more predictable input.
                    label_urls.append(data_url(original, _content_type_of(photo.original_path)))

            # A tag close-up identifies nothing — it is a rectangle of fabric with writing on
            # it — so spend the MAX_IDENTIFY_PHOTOS budget on garment shots and only fall back
            # to tag photos if that is genuinely all there is. Photos with no role sort as
            # garment shots, which is what makes this a no-op for pre-guided-capture items.
            identify_urls = [url for role, url in identify_candidates if role != "tag"]
            if not identify_urls:
                identify_urls = [url for _, url in identify_candidates]
            identify_urls = identify_urls[:MAX_IDENTIFY_PHOTOS]

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

            # Second pass: a narrow read of the care label, for the fields that are printed
            # on it. Runs BEFORE signature_for_item below, because the clothing signature
            # keys on brand AND size and returns None without both — a size discovered after
            # it would silently disable the duplicate fast-path forever.
            #
            # Best-effort, in the price_item style, with its own except. If this were allowed
            # to raise into the outer handler, an LM Studio hiccup on the label call would
            # overwrite a perfectly good identification with "identify_unavailable" and skip
            # template matching and pricing entirely. A failed label read is logged and
            # otherwise invisible: size stays null, which already means "go read the tag",
            # and inventing a third scan_error token would confuse the deploy smoke (which
            # treats identify_unavailable as fatal and low_confidence as a pass).
            if label_urls and item.item_kind == "clothing":
                try:
                    label = await read_label(label_urls)
                except HTTPException as e:
                    logger.warning(
                        "label read unavailable for item %s: %s (%s)",
                        item_id,
                        e.detail,
                        e.status_code,
                    )
                    label = None
                if label is not None:
                    # Fill, never overwrite. Identification saw the whole garment and this
                    # pass saw one label; where they disagree the first read wins, and a
                    # value already present is never blanked by a null from here.
                    item.size = item.size or label.size
                    item.size_type = item.size_type or label.size_type
                    item.material = item.material or label.material

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
            # photos; the review stack shows why identification is missing. Logged as well
            # as recorded — an outage that only shows up per-item in the DB is invisible in
            # `docker logs`, so the first sign of LM Studio being down was a user noticing.
            logger.warning(
                "identification unavailable for item %s: %s (%s)", item_id, e.detail, e.status_code
            )
            item.scan_error = f"identify_unavailable: {e.detail}"
        except Exception:
            logger.exception("scan pipeline failed for item %s", item_id)
            item.scan_error = "scan_failed"

        item.processed_at = datetime.datetime.now(datetime.UTC)
        await db.commit()


def _write(path: str, data: bytes) -> None:
    from pathlib import Path

    Path(path).write_bytes(data)


def _content_type_of(path: str) -> str:
    """MIME for an original photo, from the extension photo_store gave it.

    Inverts photo_store.ALLOWED_CONTENT_TYPES rather than re-listing the mapping, so adding
    an accepted upload type in one place cannot leave this one behind. Falls back to JPEG,
    which is what the client sends for everything.
    """
    suffix = path[path.rfind(".") :].lower()
    for mime, ext in photo_store.ALLOWED_CONTENT_TYPES.items():
        if ext == suffix:
            return mime
    return "image/jpeg"


# Vision models answer "there are no condition notes" with a placeholder rather than by
# omitting the field, and the placeholder then shipped verbatim: the first real listing ended
# with the line "Condition: N/A", visible to buyers. Treat these as absent.
_PLACEHOLDER_NOTES = {"n/a", "na", "none", "unknown", "null", "-", "--", "not applicable"}


def _is_placeholder(value: str | None) -> bool:
    return value is None or value.strip().strip(".").casefold() in _PLACEHOLDER_NOTES


def _compose_description(description: str | None, condition_notes: str | None) -> str | None:
    if _is_placeholder(condition_notes):
        return description
    if description:
        return f"{description}\n\nCondition: {condition_notes}"
    return condition_notes
