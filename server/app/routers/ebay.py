import logging
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

logger = logging.getLogger(__name__)

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
        # eBay CAN legitimately arrive here empty-handed: a declined consent, or the
        # already-granted no-reprompt path (the 2026-08-15 audit's six bare callbacks).
        # This lands in a human's browser tab, so render a page that says what happened
        # and what to do — the raw 422 JSON it used to return read as a server bug and
        # cost a full debugging session. Logged too: per-item DB state was the only trace
        # last time, and access logs alone don't explain an empty redirect.
        logger.warning(
            "eBay callback arrived without code/state — declined consent, or eBay "
            "redirected without a code (already-granted keyset / redirect-builder issue). "
            "The manual path is scripts/ebay_manual_consent.py."
        )
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;max-width:34rem;margin:3rem auto'>"
            "<h2>eBay sent you back without an authorization code</h2>"
            "<p>This usually means one of two things:</p><ul>"
            "<li>the consent was <b>declined</b> (or the sign-in didn't complete), or</li>"
            "<li>eBay <b>could not complete the redirect</b> — it sometimes skips the "
            "code when this app was already granted access, or mishandles the callback "
            "URL.</li></ul>"
            "<p>Try <b>Connect eBay</b> again from Crate's settings. If it keeps "
            "happening, use the manual path: <code>scripts/ebay_manual_consent.py</code> "
            "(see its docstring).</p>"
            "</body></html>",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
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
