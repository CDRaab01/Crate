from fastapi import APIRouter, HTTPException, Request, status
from jose import JWTError, jwt

from app.config import settings
from app.limiter import limiter
from app.schemas.auth import RefreshRequest, TokenResponse
from app.security import create_access_token, create_refresh_token

# SSO-only: no register/login/password endpoints exist. This router carries only the
# session-refresh path; sessions are minted by POST /auth/suite.
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("10/minute")
async def refresh(request: Request, req: RefreshRequest):
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
    )
    try:
        payload = jwt.decode(
            req.refresh_token, settings.secret_key, algorithms=[settings.algorithm]
        )
        if payload.get("type") != "refresh":
            raise unauthorized
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise unauthorized
    except JWTError:
        raise unauthorized

    return TokenResponse(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
    )
