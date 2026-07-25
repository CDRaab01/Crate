from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.limiter import limiter
from app.schemas.auth import SuiteLoginRequest, TokenResponse
from app.services.suite_auth import suite_login

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/suite", response_model=TokenResponse)
@limiter.limit("10/minute")
async def suite(
    request: Request,
    req: SuiteLoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Trade a Dragonfly suite token for a Crate session (the ONLY login path — SSO-only app).

    Disabled (404) unless `suite_jwks_url` + `suite_issuer` are configured.
    """
    return await suite_login(db, req.suite_token)
