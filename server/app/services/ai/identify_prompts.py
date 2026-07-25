"""Prompt + forgiving JSON parser for item identification (Phase 2).

Mirrors the suite pattern (Cookbook recipe-photo / pantry-scan prompts): constrain the model
to strict JSON, then parse defensively — vision models wrap output in prose or code fences
often enough that a naive json.loads() would fail on a large fraction of otherwise-usable
responses. Content failures degrade to a low-confidence draft; they never raise.
"""

import json
import re

from pydantic import BaseModel

from app.models.item import ITEM_CONDITIONS

MAX_TITLE = 80  # eBay's title cap
MAX_DESCRIPTION = 4000

NO_ITEM_NOTE = (
    "Couldn't identify the item from these photos — fill in the listing details by hand, "
    "or retake with better lighting and a plain background."
)

IDENTIFY_SYSTEM_PROMPT = (
    "You are an item-identification assistant for an eBay selling app. You look at photos "
    "of a single item for sale and identify it for a listing: what it is, brand and model "
    "if visible, apparent condition, and a shipping weight/size estimate. You only output "
    "JSON — never prose, never Markdown, never an explanation."
)

IDENTIFY_USER_PROMPT = (
    "Identify the item in these photos (they all show the SAME item). Respond with ONLY a "
    "JSON object, no prose and no code fences, shaped exactly like this:\n"
    "{"
    '"title": string (an eBay listing title, max 80 chars, keyword-rich, no ALL CAPS), '
    '"brand": string or null, '
    '"model": string or null, '
    '"category_hint": string (a short category phrase like "fishing lures" or '
    '"mens running shoes"), '
    '"condition": one of "new"|"like_new"|"good"|"fair"|"poor" or null, '
    '"condition_notes": string or null (visible wear, damage, missing parts), '
    '"description": string (2-5 honest sentences for the listing body), '
    '"weight_oz": number or null (estimated SHIPPING weight in ounces, including typical '
    "packaging), "
    '"dims_in": {"l": number, "w": number, "h": number} or null (estimated boxed size in '
    "inches), "
    '"confidence": one of "high"|"medium"|"low"'
    "}\n"
    "Be honest about condition — buyers return items that were oversold. If you cannot "
    "identify any item at all, respond with exactly {} and nothing else."
)


class IdentifyDraft(BaseModel):
    title: str | None = None
    brand: str | None = None
    model: str | None = None
    category_hint: str | None = None
    condition: str | None = None
    condition_notes: str | None = None
    description: str | None = None
    weight_oz: float | None = None
    dims_in: dict | None = None
    confidence: str = "low"


def build_identify_messages(image_data_urls: list[str]) -> list[dict]:
    content: list[dict] = [{"type": "text", "text": IDENTIFY_USER_PROMPT}]
    content += [{"type": "image_url", "image_url": {"url": url}} for url in image_data_urls]
    return [
        {"role": "system", "content": IDENTIFY_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", text).strip()


def _widest_object_span(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    return text[start : end + 1]


def _coerce_number(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def _coerce_dims(v) -> dict | None:
    if not isinstance(v, dict):
        return None
    dims = {axis: _coerce_number(v.get(axis)) for axis in ("l", "w", "h")}
    if any(d is None or d <= 0 for d in dims.values()):
        return None
    return dims


def _clean_str(v, limit: int) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s[:limit] if s else None


def parse_identify(raw_text: str) -> IdentifyDraft | None:
    """Best-effort parse of the model's response. Returns None (never raises) when nothing
    usable can be salvaged — the caller turns that into a low-confidence empty draft."""
    stripped = _strip_fences(raw_text)
    candidates = [stripped, _widest_object_span(stripped)]
    data = None
    for candidate in candidates:
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            break
        data = None
    if not isinstance(data, dict) or not data:
        return None

    condition = _clean_str(data.get("condition"), 16)
    if condition is not None:
        condition = condition.lower().replace(" ", "_").replace("-", "_")
        if condition not in ITEM_CONDITIONS:
            condition = None

    confidence = _clean_str(data.get("confidence"), 8)
    confidence = confidence.lower() if confidence else "low"
    if confidence not in ("high", "medium", "low"):
        confidence = "low"

    weight = _coerce_number(data.get("weight_oz"))
    if weight is not None and not (0 < weight <= 2400):  # 150 lb parcel ceiling
        weight = None

    title = _clean_str(data.get("title"), MAX_TITLE)
    description = _clean_str(data.get("description"), MAX_DESCRIPTION)
    if title is None and description is None:
        return None

    return IdentifyDraft(
        title=title,
        brand=_clean_str(data.get("brand"), 64),
        model=_clean_str(data.get("model"), 64),
        category_hint=_clean_str(data.get("category_hint"), 64),
        condition=condition,
        condition_notes=_clean_str(data.get("condition_notes"), 500),
        description=description,
        weight_oz=weight,
        dims_in=_coerce_dims(data.get("dims_in")),
        confidence=confidence,
    )
