import shutil
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.limiter import limiter
from app.models.item import ITEM_STATUSES, Item, ItemPhoto
from app.schemas.item import ItemOut, ItemUpdate, ScanAccepted
from app.security import CurrentUser
from app.services import photo_store, scan_pipeline

router = APIRouter(prefix="/items", tags=["items"])

MAX_SCAN_PHOTOS = 8


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
):
    """Batch-capture entry point: 1-8 photos of ONE item → a draft that processes in the
    background (cleanup → identify). Poll GET /items/{id} until processed_at is set."""
    if not 1 <= len(photos) <= MAX_SCAN_PHOTOS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Send 1-{MAX_SCAN_PHOTOS} photos"
        )
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
        db.add(ItemPhoto(item_id=item.id, order=order, original_path=path))
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
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))

    fields = req.model_dump(exclude_unset=True)
    for name, value in fields.items():
        if name in ("title", "description", "brand", "model", "category_id") and value == "":
            value = None
        if name == "dims_in_est" and value is not None:
            value = dict(value)
        setattr(item, name if name != "dims_in_est" else "dims_in_est", value)
    await db.commit()
    return await _owned_item(db, user.id, item_id)


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
