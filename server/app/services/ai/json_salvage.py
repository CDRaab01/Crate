"""Salvaging usable JSON out of a vision model's reply.

Shared by every AI prompt module. Vision models wrap their output in prose or code fences
often enough that a naive json.loads() would throw away a large fraction of otherwise-fine
responses, so each parser tries the stripped text first and then the widest {...} span.

This lives in its own module because there is now more than one prompt (item identification
and the narrow care-label read) and the salvage layer is load-bearing: a fix here — a new
fence dialect, a new way a model likes to preamble — has to apply to all of them at once,
not to whichever one someone remembered to patch.

Deliberately dumb and total: nothing in here raises, and every function returns None rather
than a partial result, so a caller can always fall back to "nothing usable came back".
"""

import re

# Matches an opening ```/```json fence at the start of a line and a closing fence at the end.
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def strip_fences(text: str) -> str:
    """Drop Markdown code fences a model wrapped its JSON in."""
    return _FENCE_RE.sub("", text).strip()


def widest_object_span(text: str) -> str | None:
    """The outermost {...} in `text`, or None if there isn't one.

    Widest rather than first: models that preamble ("Here's the JSON:") also sometimes
    postamble, and the object we want is the whole thing between the first { and the last }.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    return text[start : end + 1]


def clean_str(value: object, limit: int) -> str | None:
    """Trim to a string capped at `limit`, or None when it's empty/absent.

    Empty-after-strip collapses to None on purpose: "" and "   " mean the model had nothing,
    and storing them would read downstream as "a human already filled this in".
    """
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None
