"""The 15-minute background poller: orders + buyer messages for every connected user.

Started from the app's lifespan; a cycle failure logs and waits for the next tick —
one bad poll must never kill the loop. `poll_interval_minutes = 0` disables it
entirely (tests, CI, and any deploy that predates eBay credentials)."""

import asyncio
import logging

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.ebay_credentials import EbayCredentials
from app.services.ebay import fulfillment, oauth

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None


async def poll_once() -> dict:
    """One full cycle across all connected users. Returns counts (for logs and tests)."""
    totals = {"sales": 0, "messages": 0}
    async with AsyncSessionLocal() as db:
        user_ids = (await db.execute(select(EbayCredentials.user_id))).scalars().all()
    for user_id in user_ids:
        async with AsyncSessionLocal() as db:
            try:
                totals["sales"] += await fulfillment.poll_orders(db, user_id)
                totals["messages"] += await fulfillment.poll_messages(db, user_id)
            except Exception:
                logger.exception("poll cycle failed for user %s", user_id)
    return totals


async def _loop() -> None:
    while True:
        await asyncio.sleep(settings.poll_interval_minutes * 60)
        try:
            totals = await poll_once()
            if totals["sales"] or totals["messages"]:
                logger.info("poll cycle: %s", totals)
        except Exception:
            logger.exception("poll cycle crashed; continuing")


def start() -> None:
    global _task
    if settings.poll_interval_minutes <= 0 or not oauth.configured():
        logger.info("order poller disabled (interval=0 or eBay unconfigured)")
        return
    if _task is None or _task.done():
        _task = asyncio.get_event_loop().create_task(_loop())


def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
