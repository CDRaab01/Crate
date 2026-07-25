import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.duplicate_template import DuplicateTemplate
from app.schemas.template import TemplateOut
from app.security import CurrentUser

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=list[TemplateOut])
async def list_templates(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return (
        (
            await db.execute(
                select(DuplicateTemplate)
                .where(DuplicateTemplate.user_id == user.id)
                .order_by(DuplicateTemplate.use_count.desc())
            )
        )
        .scalars()
        .all()
    )


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Retire a stale pattern; items keep template_id = NULL via the FK's SET NULL."""
    template = (
        await db.execute(
            select(DuplicateTemplate).where(
                DuplicateTemplate.id == template_id, DuplicateTemplate.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    await db.delete(template)
    await db.commit()
