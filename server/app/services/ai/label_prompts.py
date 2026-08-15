"""Prompt + parser for reading a garment's care/size label. One job, deliberately.

Why this exists as a second call instead of more words in identify_prompts. That prompt asks
for roughly twenty things at once — title, condition, weight, boxed dimensions, brand,
colour, style, fit, sleeve length, size — and size is what falls out. Measured over three
runs against eight real tag photographs, it read ~1 in 6 legible sizes. Asked the same
question in isolation ("what size is printed on this label?"), the same model on the same
images read 3 of 4, and correctly returned nothing for both labels that had no size on them.

The tempting fix — telling the omnibus prompt to try harder — was measured and rejected: it
produced no recall gain AND a reproducible wrong answer, confidently reporting "M" for a
label whose "S" is circled, in three runs out of three. That is the exact failure the
never-infer rule exists to prevent, so the rule below is carried over verbatim rather than
softened. A wrong size ships the wrong garment to a buyer; a null just sends a human to the
tag while it is still in reach.

Scope is what is PRINTED on the label: size, size_type, material. Not brand (often on a
separate woven tab and already read acceptably), not measurements (a vision model cannot
hold a tape measure — the omission is deliberate and documented in identify_prompts too).
"""

import json

from pydantic import BaseModel

from app.apparel import SIZE_TYPES, normalize_enum
from app.services.ai.json_salvage import clean_str, strip_fences, widest_object_span

LABEL_SYSTEM_PROMPT = (
    "You transcribe clothing care and size labels. You are given close-up photos of a "
    "garment's sewn-in label and you report only what is actually printed or woven on it, "
    "character for character. You are not identifying the garment and you are not "
    "estimating anything. You only output JSON — never prose, never Markdown, never an "
    "explanation."
)

LABEL_USER_PROMPT = (
    "These photos show a clothing label. Respond with ONLY a JSON object, no prose and no "
    "code fences, shaped exactly like this:\n"
    "{"
    '"size": string or null (EXACTLY as printed, e.g. "M", "X-LARGE", "32x34", "10.5", "中"), '
    '"size_type": one of "regular"|"petite"|"plus"|"big_tall"|"juniors"|"maternity" or null, '
    '"material": string or null (the fabric content as printed, e.g. "100% Cotton", '
    '"60% Cotton 40% Polyester")'
    "}\n"
    "Transcribe, do not interpret. Copy the characters you can actually see, including a "
    "non-Latin size character. Do not convert between sizing systems, do not expand or "
    "abbreviate, and do not translate.\n"
    "If a value is not printed on the label, or you cannot read it clearly, use null for "
    "that field. NEVER infer a garment's size from how it looks — a wrong size is a returned "
    "item; a null just means a human reads the tag. A label showing only a brand name, or "
    "only laundry-care symbols, has no size: return null.\n"
    'If the label shows a full size run (for example "XS S M L XL XXL") with exactly one '
    "option circled, boxed, ticked or otherwise marked, report the marked one. If several "
    "are marked, or none is, set size to null — reporting the middle of a run is a guess.\n"
    "If none of these three values is readable, respond with exactly {} and nothing else."
)


class LabelDraft(BaseModel):
    """What a label actually said. Every field optional — absent means "not printed or not
    legible", which is a meaningful answer here, not a failure."""

    size: str | None = None
    size_type: str | None = None
    material: str | None = None

    def is_empty(self) -> bool:
        return self.size is None and self.size_type is None and self.material is None


def build_label_messages(image_data_urls: list[str]) -> list[dict]:
    content: list[dict] = [{"type": "text", "text": LABEL_USER_PROMPT}]
    content += [{"type": "image_url", "image_url": {"url": url}} for url in image_data_urls]
    return [
        {"role": "system", "content": LABEL_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def parse_label(raw_text: str) -> LabelDraft | None:
    """Best-effort parse of the label reply. Returns None (never raises) when nothing usable
    came back, so the caller can leave the item's fields exactly as identification left them.

    Same salvage contract as parse_identify: fences stripped, widest {...} span as a
    fallback, unrecognised size_type dropped rather than rejected. Field caps match the
    column widths in models/item.py so a chatty model cannot overflow a write.
    """
    stripped = strip_fences(raw_text)
    data = None
    for candidate in (stripped, widest_object_span(stripped)):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            data = parsed
            break
    if not isinstance(data, dict) or not data:
        return None

    draft = LabelDraft(
        size=clean_str(data.get("size"), 32),
        size_type=normalize_enum(data.get("size_type"), SIZE_TYPES),
        material=clean_str(data.get("material"), 96),
    )
    # An all-null draft is indistinguishable from not having asked, and returning None lets
    # the caller skip the merge entirely.
    return None if draft.is_empty() else draft
