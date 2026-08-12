"""Duplicate-template signatures — pure and exhaustively table-tested (CLAUDE.md §4/§9).

A signature is NORMALIZED TEXT from brand+model tokens: casefolded, alphanumerics only,
deduped, order-stable. Not embeddings (LM Studio vision gives no image-embedding path and
text is testable). Deviation from the §4 sketch, flagged in ARCHITECTURE.md: category
tokens are NOT included — the vision category_hint is transient (never stored on the
item), so a sale-time signature could never reproduce a capture-time one. Brand+model is
the natural "same lure model sold before" key; items without either simply never match.

Clothing takes a wider key (see build_apparel_signature): garments seldom have a "model", so
brand+model alone would collapse every shirt of a brand into one template.
"""

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(parts) -> str | None:
    tokens: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not part:
            continue
        for token in _TOKEN_RE.findall(str(part).casefold()):
            if token not in seen:
                seen.add(token)
                tokens.append(token)
    return " ".join(tokens) or None


def build_signature(brand: str | None, model: str | None) -> str | None:
    """General-goods signature: order-stable, deduped, casefolded brand+model tokens — or
    None when there's nothing identifying to match on (no brand AND no model)."""
    return _tokenize((brand, model))


def build_apparel_signature(
    brand: str | None,
    model: str | None,
    style: str | None,
    size: str | None,
    department: str | None,
) -> str | None:
    """Clothing signature — brand+model+style+size+department, and None unless BOTH brand
    and size are known.

    Garments rarely have a "model", so the general signature would degrade to the bare brand
    and collapse every Nike shirt the user has ever sold into one template — which would then
    overwrite an unrelated garment's title and description at capture time. Size is the
    discriminator that makes a template safe to reuse: the same style in M and L are
    different listings with different item specifics, so reusing one across sizes would post
    the wrong size. No size yet (nobody has read the tag) ⇒ no match, and identification
    simply stands on its own.
    """
    if not (brand and brand.strip()) or not (size and str(size).strip()):
        return None
    return _tokenize((brand, model, style, size, department))


def signature_for_item(item) -> str | None:
    """The signature for an item, dispatched on kind. Both call sites — capture-time
    matching and sale-time template creation — go through here so they cannot drift."""
    if item.item_kind == "clothing":
        return build_apparel_signature(
            item.brand, item.model, item.style, item.size, item.department
        )
    return build_signature(item.brand, item.model)
