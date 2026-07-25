"""Duplicate-template signatures — pure and exhaustively table-tested (CLAUDE.md §4/§9).

A signature is NORMALIZED TEXT from brand+model tokens: casefolded, alphanumerics only,
deduped, order-stable. Not embeddings (LM Studio vision gives no image-embedding path and
text is testable). Deviation from the §4 sketch, flagged in ARCHITECTURE.md: category
tokens are NOT included — the vision category_hint is transient (never stored on the
item), so a sale-time signature could never reproduce a capture-time one. Brand+model is
the natural "same lure model sold before" key; items without either simply never match.
"""

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def build_signature(brand: str | None, model: str | None) -> str | None:
    """Order-stable, deduped, casefolded token signature — or None when there's nothing
    identifying to match on (no brand AND no model)."""
    tokens: list[str] = []
    seen: set[str] = set()
    for part in (brand, model):
        if not part:
            continue
        for token in _TOKEN_RE.findall(part.casefold()):
            if token not in seen:
                seen.add(token)
                tokens.append(token)
    return " ".join(tokens) or None
