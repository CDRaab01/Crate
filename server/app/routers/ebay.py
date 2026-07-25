from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.limiter import limiter
from app.models.ebay_credentials import EbayCredentials
from app.security import CurrentUser
from app.services.ebay import oauth

router = APIRouter(prefix="/ebay", tags=["ebay"])


@router.get("/connect")
@limiter.limit("10/minute")
async def connect(request: Request, user: CurrentUser):
    """Start the one-time seller consent: the app opens the returned URL in a browser on
    the tailnet; eBay redirects back to /ebay/callback."""
    if not oauth.configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "eBay keyset/RuName/Fernet key not configured — see server/.env.example",
        )
    return {"authorize_url": oauth.authorize_url(str(user.id))}


@router.get("/callback", response_class=HTMLResponse)
async def callback(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    code: str | None = None,
    state: str | None = None,
):
    """eBay's redirect target (unauthenticated — the browser carries no bearer token; the
    one-time `state` minted by /ebay/connect is what proves the session)."""
    if not code or not state:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Missing code/state")
    user_id = oauth.consume_state(state)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown or expired state")
    await oauth.exchange_code(db, user_id, code)
    return HTMLResponse(
        "<html><body style='font-family:sans-serif'>"
        "<h2>eBay connected ✔</h2><p>You can close this tab and return to Crate.</p>"
        "</body></html>"
    )


@router.get("/status")
async def connection_status(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Connection state for Settings — surfaces refresh-token expiry well before it hits
    (~18-month lifetime)."""
    creds = (
        await db.execute(select(EbayCredentials).where(EbayCredentials.user_id == user.id))
    ).scalar_one_or_none()
    return {
        "configured": oauth.configured(),
        "connected": creds is not None,
        "environment": creds.environment if creds else None,
        "access_expires_at": creds.expires_at.isoformat() if creds else None,
        "refresh_expires_at": creds.refresh_expires_at.isoformat() if creds else None,
    }


@router.delete("/connection", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    creds = (
        await db.execute(select(EbayCredentials).where(EbayCredentials.user_id == user.id))
    ).scalar_one_or_none()
    if creds is not None:
        await db.delete(creds)
        await db.commit()
