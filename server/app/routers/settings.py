import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user_settings import UserSettings
from app.security import CurrentUser

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    drops_enabled: bool
    drop_interval_days: int
    drop_step_percent: Decimal
    shipping_preference: str
    ntfy_topic: str | None


class SettingsUpdate(BaseModel):
    """These knobs are what make the unattended drop scheduler 'deterministic policy the
    user configured' — bounds keep the policy sane (a 95% daily drop is a typo, not a
    strategy)."""

    drops_enabled: bool | None = None
    drop_interval_days: int | None = Field(default=None, ge=1, le=90)
    drop_step_percent: Decimal | None = Field(default=None, ge=1, le=50)
    shipping_preference: str | None = Field(default=None, pattern="^(cheapest|fastest)$")
    ntfy_topic: str | None = Field(default=None, max_length=128)


async def _settings_row(db: AsyncSession, user_id) -> UserSettings:
    row = (
        await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:  # pre-SSO-seed accounts (tests, migrations) — create on first touch
        row = UserSettings(user_id=user_id)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


@router.get("", response_model=SettingsOut)
async def get_settings(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _settings_row(db, user.id)


@router.patch("", response_model=SettingsOut)
async def update_settings(
    req: SettingsUpdate,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    row = await _settings_row(db, user.id)
    for name, value in req.model_dump(exclude_none=True).items():
        setattr(row, name, value)
    await db.commit()
    return row
