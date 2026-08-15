"""LM Studio vision client (item identification). Mirrors Cookbook's app/services/ai/vision.py:
local OpenAI-compatible chat-completions call, low temperature for faithfulness over
creativity, transport failures mapped to clean HTTP statuses so the client can distinguish
"not configured/unreachable" from "photos unreadable"."""

import base64

import httpx
from fastapi import HTTPException, status

from app.config import settings
from app.services.ai.identify_prompts import (
    IdentifyDraft,
    build_identify_messages,
    parse_identify,
)
from app.services.ai.label_prompts import (
    LabelDraft,
    build_label_messages,
    parse_label,
)


def data_url(image_bytes: bytes, content_type: str) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


async def _chat_vision(messages: list[dict], client: httpx.AsyncClient | None) -> str:
    """One multimodal chat-completions round trip to LM Studio, returning the raw model
    text. ``client`` is an injection seam for tests (httpx.MockTransport) — production
    calls always go through the default, real-network client."""
    owns_client = client is None
    active = client or httpx.AsyncClient(timeout=settings.lm_studio_timeout)

    try:
        try:
            response = await active.post(
                f"{settings.lm_studio_base_url}/chat/completions",
                json={
                    "model": settings.lm_studio_vision_model,
                    "messages": messages,
                    "temperature": 0.2,
                },
            )
            response.raise_for_status()
        finally:
            if owns_client:
                await active.aclose()
    except httpx.TimeoutException as e:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="LM Studio timed out — the vision model may still be loading.",
        ) from e
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LM Studio rejected the request.",
        ) from e
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Couldn't reach LM Studio. Is it running?",
        ) from e

    body = response.json()
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LM Studio returned a malformed response.",
        ) from e
    if not isinstance(content, str):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LM Studio returned a malformed response.",
        )
    return content


async def identify_item(
    image_data_urls: list[str],
    client: httpx.AsyncClient | None = None,
) -> IdentifyDraft:
    """Identify one item from 1-N photos. Content failures degrade to a low-confidence
    empty draft; transport failures raise (503/504/502) for the pipeline to record."""
    messages = build_identify_messages(image_data_urls)
    raw_text = await _chat_vision(messages, client)
    draft = parse_identify(raw_text)
    if draft is None:
        return IdentifyDraft(confidence="low")
    return draft


async def read_label(
    image_data_urls: list[str],
    client: httpx.AsyncClient | None = None,
) -> LabelDraft | None:
    """Read size/size_type/material off a care-label photo, or None if nothing was legible.

    Lives here rather than beside its prompt because `_chat_vision` is module-private and
    reaching across modules for a `_`-prefixed name would be a new precedent; keeping it in
    this file means the transport, timeout and 503/504/502 mapping have exactly one
    implementation. Transport failures raise like identify_item's — the caller decides
    whether that is fatal, and in the scan pipeline it deliberately is not.
    """
    messages = build_label_messages(image_data_urls)
    raw_text = await _chat_vision(messages, client)
    return parse_label(raw_text)
