import shutil
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import httpx

from app.apparel import PHOTO_ROLES, normalize_enum
from app.config import settings
from app.database import get_db
from app.limiter import limiter
from app.models.item import ITEM_STATUSES, Item, ItemPhoto
from app.models.price_event import PriceEvent
from app.models.sale import Sale
from app.pricing import browse
from app.pricing import service as pricing_service
from app.pricing.comps import compute_prices
from app.schemas.item import CompOut, CompsOut, ItemOut, ItemUpdate, SaleOut, ScanAccepted
from app.schemas.template import PriceEventOut
from app.security import CurrentUser
from app.services import item_lifecycle, photo_store, scan_pipeline
from app.services.ebay import sell

router = APIRouter(prefix="/items", tags=["items"])

MAX_SCAN_PHOTOS = 8

# Nullable text fields where the suite's ""-clears convention applies (see update_item).
CLEARABLE_TEXT_FIELDS = frozenset(
    {
        "title",
        "description",
        "brand",
        "model",
        "category_id",
        "size",
        "color",
        "material",
        "style",
        "storage_location",
    }
)
# Apparel enums + measurements: normalized/validated separately, so the generic PATCH loop
# skips them rather than writing the raw request value through.
APPAREL_ENUM_FIELDS = ("item_kind", "size_type", "department", "fit", "sleeve_length")
VALIDATED_FIELDS = frozenset({*APPAREL_ENUM_FIELDS, "measurements_in"})


async def _owned_item(db: AsyncSession, user_id: uuid.UUID, item_id: uuid.UUID) -> Item:
    item = (
        await db.execute(
            select(Item)
            .options(selectinload(Item.photos))
            .where(Item.id == item_id, Item.user_id == user_id)
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    return item


@router.post("/scan", response_model=ScanAccepted, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("20/minute")
async def scan(
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    background: BackgroundTasks,
    photos: list[UploadFile],
    roles: Annotated[list[str] | None, Form()] = None,
):
    """Batch-capture entry point: 1-8 photos of ONE item → a draft that processes in the
    background (cleanup → identify). Poll GET /items/{id} until processed_at is set.

    `roles` is optional and index-aligned with `photos` (front/back/detail/tag), set by the
    guided capture flow. Photo order is already purely positional here, so a parallel list
    is the consistent way to carry it. Omitting it entirely is valid and means "unknown" —
    which keeps every pre-guided-capture client working, including the deploy smoke.
    """
    if not 1 <= len(photos) <= MAX_SCAN_PHOTOS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Send 1-{MAX_SCAN_PHOTOS} photos"
        )
    # Index pairing is the only sane contract for parallel lists: zipping a short list would
    # silently attach roles to the wrong photos, and a mislabelled tag is worse than none.
    if roles and len(roles) != len(photos):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Send one role per photo or none at all ({len(roles)} roles, {len(photos)} photos)",
        )
    # Reject, don't degrade. Vision output is salvaged because the model is doing its best
    # with a photograph; a role is a value OUR client chose, so an unrecognised one is a
    # contract bug worth surfacing loudly rather than silently storing as unknown.
    normalized_roles: list[str | None] = [None] * len(photos)
    for index, raw in enumerate(roles or []):
        role = normalize_enum(raw, PHOTO_ROLES)
        if role is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Unknown photo role {raw!r} (expected one of {', '.join(PHOTO_ROLES)})",
            )
        normalized_roles[index] = role

    payloads: list[tuple[bytes, str]] = []
    for upload in photos:
        if upload.content_type not in photo_store.ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Unsupported photo type {upload.content_type!r} (JPEG/PNG/WebP only)",
            )
        data = await upload.read()
        if len(data) > settings.photo_max_bytes:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                "Photo exceeds the size cap — the app should downscale before upload",
            )
        payloads.append((data, upload.content_type))

    item = Item(user_id=user.id)
    db.add(item)
    await db.flush()
    for order, (data, content_type) in enumerate(payloads):
        path = photo_store.save_original(item.id, order, data, content_type)
        db.add(
            ItemPhoto(
                item_id=item.id,
                order=order,
                role=normalized_roles[order],
                original_path=path,
            )
        )
    await db.commit()

    background.add_task(scan_pipeline.process_item, item.id)
    return ScanAccepted(id=item.id, status="draft", photo_count=len(payloads))


@router.get("", response_model=list[ItemOut])
async def list_items(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: str | None = None,
):
    if status_filter is not None and status_filter not in ITEM_STATUSES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown status")
    query = (
        select(Item)
        .options(selectinload(Item.photos))
        .where(Item.user_id == user.id)
        .order_by(Item.created_at.desc())
    )
    if status_filter is not None:
        query = query.where(Item.status == status_filter)
    return (await db.execute(query)).scalars().all()


@router.get("/{item_id}", response_model=ItemOut)
async def get_item(
    item_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _owned_item(db, user.id, item_id)


@router.patch("/{item_id}", response_model=ItemOut)
async def update_item(
    item_id: uuid.UUID,
    req: ItemUpdate,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Review-stack edits. PATCH clearing convention: omitted = untouched, "" = clear."""
    item = await _owned_item(db, user.id, item_id)
    try:
        req.validated_condition()
        enums = req.validated_enums()
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))

    # Suite PATCH convention: null (or omitted) = untouched, "" = clear. exclude_none —
    # not exclude_unset — because kotlinx.serialization clients encode absent fields as
    # explicit nulls.
    fields = req.model_dump(exclude_none=True)
    for name, value in fields.items():
        if name in VALIDATED_FIELDS:  # applied below, already normalized
            continue
        if name in CLEARABLE_TEXT_FIELDS and value == "":
            value = None
        if name == "dims_in_est":
            value = dict(value)
        setattr(item, name, value)

    # Enums land normalized ("Big & Tall" -> "big_tall"); an empty string clears them, except
    # item_kind which is NOT NULL and so only ever moves between known kinds.
    for name in APPAREL_ENUM_FIELDS:
        raw = getattr(req, name)
        if raw == "" and name != "item_kind":
            setattr(item, name, None)
        elif name in enums:
            setattr(item, name, enums[name])
    # An explicitly-sent measurements body applies normalized; all-empty clears (the generic
    # loop can't express that, since "nothing measured" normalizes to None).
    if req.measurements_in is not None:
        item.measurements_in = req.validated_measurements()

    await db.commit()
    return await _owned_item(db, user.id, item_id)


@router.post("/{item_id}/post", response_model=ItemOut)
@limiter.limit("20/minute")
async def post_item(
    request: Request,
    item_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """The explicit approve tap: draft → live eBay listing (EPS photos → inventory →
    offer → publish). Money-adjacent, so it NEVER happens unattended (CLAUDE.md §9)."""
    item = await _owned_item(db, user.id, item_id)
    if item.status != "draft":
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Only drafts can be posted (status={item.status!r})"
        )
    await sell.publish_item(db, item)
    await item_lifecycle.transition(db, item, "active")
    await db.commit()
    return await _owned_item(db, user.id, item_id)


@router.post("/{item_id}/delist", response_model=ItemOut)
@limiter.limit("20/minute")
async def delist_item(
    request: Request,
    item_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Withdraw the live offer; the item can be relisted or deleted afterwards."""
    item = await _owned_item(db, user.id, item_id)
    if item.status != "active":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Only active listings can be delisted (status={item.status!r})",
        )
    await sell.end_listing(db, item)
    await item_lifecycle.transition(db, item, "delisted")
    await db.commit()
    return await _owned_item(db, user.id, item_id)


@router.post("/{item_id}/relist", response_model=ItemOut)
@limiter.limit("20/minute")
async def relist_item(
    request: Request,
    item_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Put a delisted (or returned) item back on eBay — the existing offer republishes
    with a fresh listingId. Explicit tap, like every listing write."""
    item = await _owned_item(db, user.id, item_id)
    if item.status not in ("delisted", "returned"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Only delisted/returned items can be relisted (status={item.status!r})",
        )
    await sell.republish_offer(db, item)
    await item_lifecycle.transition(db, item, "active")
    await db.commit()
    return await _owned_item(db, user.id, item_id)


@router.get("/{item_id}/comps", response_model=CompsOut)
@limiter.limit("30/minute")
async def comps(
    request: Request,
    item_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Live comp evidence for the review screen — ACTIVE-market prices, labeled honestly
    (sold-comp data is partner-only and not available). 503 until an eBay keyset exists."""
    if not browse.configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "eBay keyset not configured — comp research is unavailable",
        )
    item = await _owned_item(db, user.id, item_id)
    try:
        found = await pricing_service.fetch_comps(item)
    except httpx.HTTPError:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "eBay comp search failed")
    suggestion = compute_prices(found)
    top = sorted(found, key=lambda c: c.price)[:10]
    return CompsOut(
        comps=[
            CompOut(title=c.title, price=c.price, condition=c.condition, url=c.url) for c in top
        ],
        quick_sale=suggestion.quick_sale if suggestion else None,
        patient=suggestion.patient if suggestion else None,
        comp_count=suggestion.comp_count if suggestion else 0,
    )


@router.get("/{item_id}/sale", response_model=SaleOut)
async def item_sale(
    item_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """The sale record for a sold item — buyer address + ship state for the Ship screen."""
    await _owned_item(db, user.id, item_id)
    sale = (await db.execute(select(Sale).where(Sale.item_id == item_id))).scalar_one_or_none()
    if sale is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item has no sale yet")
    return sale


@router.get("/{item_id}/price-events", response_model=list[PriceEventOut])
async def price_events(
    item_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Price history for the detail screen — every drop the scheduler (or the user) made."""
    await _owned_item(db, user.id, item_id)
    return (
        (
            await db.execute(
                select(PriceEvent)
                .where(PriceEvent.item_id == item_id)
                .order_by(PriceEvent.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


@router.get("/{item_id}/photos/{photo_id}/file")
async def photo_file(
    item_id: uuid.UUID,
    photo_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Serve the photo binary (cleaned when available, else the original) — the review
    stack's image source. Owner-scoped like everything else."""
    item = await _owned_item(db, user.id, item_id)
    photo = next((p for p in item.photos if p.id == photo_id), None)
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    path = photo.cleaned_path or photo.original_path
    if not Path(path).is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo file missing")
    media_type = "image/png" if path.endswith(".png") else "image/jpeg"
    return FileResponse(path, media_type=media_type)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Dismiss a draft (or a delisted item). Anything live on eBay must be delisted first —
    deleting the local row while the listing is up would orphan it."""
    item = await _owned_item(db, user.id, item_id)
    if item.status not in ("draft", "delisted"):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Can't delete an item with status {item.status!r}"
        )
    await db.delete(item)
    await db.commit()
    # Best-effort file cleanup; the DB row is the source of truth.
    shutil.rmtree(Path(settings.photos_dir) / str(item_id), ignore_errors=True)
