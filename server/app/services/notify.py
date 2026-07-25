"""ntfy pushes (Dragonfly digest precedent): silently off when unset, never raises into
callers — a dead notification service must not break a sale poll or a price drop."""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def enabled() -> bool:
    return bool(settings.ntfy_base_url and settings.ntfy_topic)


async def push(
    title: str,
    body: str,
    *,
    topic: str | None = None,
    priority: str = "default",
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Send one notification. Returns False (and logs) on any failure — best-effort only."""
    target_topic = topic or settings.ntfy_topic
    if not settings.ntfy_base_url or not target_topic:
        return False
    owns = client is None
    active = client or httpx.AsyncClient(timeout=settings.external_timeout_seconds)
    try:
        resp = await active.post(
            f"{settings.ntfy_base_url.rstrip('/')}/{target_topic}",
            content=body.encode(),
            headers={"Title": title, "Priority": priority},
        )
        resp.raise_for_status()
        return True
    except httpx.HTTPError:
        logger.warning("ntfy push failed (title=%r)", title, exc_info=True)
        return False
    finally:
        if owns:
            await active.aclose()
