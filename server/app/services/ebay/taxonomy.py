"""eBay category suggestions for the review screen's category dropdown.

Why this is not a Gemma job. eBay publishes an authoritative mapping from item text to
category, and it is versioned (the tree answering today is v134). Asking a vision model for
a numeric category id would invite a plausible-looking hallucination that fails at publish,
and any id it memorised would rot silently as eBay reorganises the tree. So the division is:
Gemma supplies the *words* (title, style, department, brand) and eBay supplies the *id*.

Uses the CLIENT-CREDENTIALS app token, not the seller's user token: suggestions are public
reference data, and requiring the one-time seller consent to fill a dropdown would make the
review screen unusable on any install that has not connected eBay yet.
"""

from dataclasses import dataclass

import httpx

from app.config import settings
from app.models.item import Item
from app.pricing import browse

_TAXONOMY_HOSTS = {
    "production": "https://api.ebay.com",
    "sandbox": "https://api.sandbox.ebay.com",
}


@dataclass(frozen=True)
class CategorySuggestion:
    category_id: str
    name: str
    path: str  # human-readable ancestry, e.g. "Men > Men's Clothing > Shirts"


def configured() -> bool:
    return browse.configured()


def query_for(item: Item) -> str:
    """The text eBay matches against.

    Title first because it is the richest signal, then the attributes a title may omit.
    Deduplicated case-insensitively so "Polo" in both the title and `style` does not get
    double weight, and capped because the endpoint is a query string, not an essay.
    """
    parts = [item.title, item.brand, item.style, item.department]
    seen: set[str] = set()
    words: list[str] = []
    for part in parts:
        for word in (part or "").split():
            if word.casefold() not in seen:
                seen.add(word.casefold())
                words.append(word)
    return " ".join(words)[:350]


async def suggest_categories(
    item: Item, client: httpx.AsyncClient | None = None, limit: int = 5
) -> list[CategorySuggestion]:
    """Ranked category suggestions, best first. Raises httpx errors for the caller to map."""
    query = query_for(item)
    if not query:
        return []

    owns_client = client is None
    active = client or httpx.AsyncClient(timeout=settings.external_timeout_seconds)
    try:
        token = await browse._app_token(active)
        host = _TAXONOMY_HOSTS.get(settings.ebay_environment, _TAXONOMY_HOSTS["sandbox"])
        headers = {"Authorization": f"Bearer {token}"}

        tree = await active.get(
            f"{host}/commerce/taxonomy/v1/get_default_category_tree_id",
            headers=headers,
            params={"marketplace_id": settings.ebay_marketplace_id},
        )
        tree.raise_for_status()
        tree_id = tree.json().get("categoryTreeId", "0")

        resp = await active.get(
            f"{host}/commerce/taxonomy/v1/category_tree/{tree_id}/get_category_suggestions",
            headers=headers,
            params={"q": query},
        )
        resp.raise_for_status()

        suggestions = []
        for entry in resp.json().get("categorySuggestions", [])[:limit]:
            category = entry.get("category", {})
            category_id = category.get("categoryId")
            if not category_id:
                continue
            # Ancestors come back deepest-first; reversed reads the way a breadcrumb does.
            ancestors = entry.get("categoryTreeNodeAncestors", [])
            path = " > ".join(
                a.get("categoryName", "") for a in reversed(ancestors) if a.get("categoryName")
            )
            suggestions.append(
                CategorySuggestion(
                    category_id=str(category_id),
                    name=category.get("categoryName", str(category_id)),
                    path=path,
                )
            )
        return suggestions
    finally:
        if owns_client:
            await active.aclose()


@dataclass(frozen=True)
class AspectValues:
    """The permitted values for one eBay item aspect in a given category."""

    name: str
    required: bool
    selection_only: bool  # True ⇒ eBay rejects anything not in `values`
    values: list[str]


async def aspect_values(
    category_id: str, client: httpx.AsyncClient | None = None
) -> list[AspectValues]:
    """What eBay will accept for each aspect of `category_id`.

    Read live rather than hardcoded because eBay is actively tightening it: the Size
    Standardization programme (full enforcement August 2026) removes custom size values and
    blocks or holds listings that carry non-standard ones. A vocabulary copied into this repo
    would be a snapshot of a moving target — and the failure mode is a listing pulled from
    the site, not a test going red.
    """
    owns_client = client is None
    active = client or httpx.AsyncClient(timeout=settings.external_timeout_seconds)
    try:
        token = await browse._app_token(active)
        host = _TAXONOMY_HOSTS.get(settings.ebay_environment, _TAXONOMY_HOSTS["sandbox"])
        headers = {"Authorization": f"Bearer {token}"}

        tree = await active.get(
            f"{host}/commerce/taxonomy/v1/get_default_category_tree_id",
            headers=headers,
            params={"marketplace_id": settings.ebay_marketplace_id},
        )
        tree.raise_for_status()
        tree_id = tree.json().get("categoryTreeId", "0")

        resp = await active.get(
            f"{host}/commerce/taxonomy/v1/category_tree/{tree_id}/get_item_aspects_for_category",
            headers=headers,
            params={"category_id": category_id},
        )
        resp.raise_for_status()

        found = []
        for aspect in resp.json().get("aspects", []):
            constraint = aspect.get("aspectConstraint", {})
            found.append(
                AspectValues(
                    name=aspect.get("localizedAspectName", ""),
                    required=bool(constraint.get("aspectRequired")),
                    selection_only=constraint.get("aspectMode") == "SELECTION_ONLY",
                    values=[
                        v["localizedValue"]
                        for v in aspect.get("aspectValues", [])
                        if v.get("localizedValue")
                    ],
                )
            )
        return found
    finally:
        if owns_client:
            await active.aclose()


def match_standard_size(tag_text: str | None, permitted: list[str]) -> str | None:
    """The permitted value a tag reading unambiguously IS, or None to ask the human.

    Deliberately narrow. It resolves case and spacing ("small" → "S", " M " → "M") and the
    long forms eBay itself normalizes, and stops there. A tag reading "M/L" is genuinely two
    sizes, "EUR 30 / US 30 / CN 170/76A" is three systems, and "別大" is not in any Latin
    vocabulary — guessing at those is how a buyer receives the wrong garment, so they come
    back as None and become a dropdown the human answers.
    """
    if not tag_text or not permitted:
        return None
    cleaned = tag_text.strip()
    by_fold = {value.casefold(): value for value in permitted}

    if cleaned.casefold() in by_fold:
        return by_fold[cleaned.casefold()]

    # eBay's own documented normalization: the spelled-out forms map to the letter codes.
    long_forms = {
        "extra extra small": "XXS",
        "extra small": "XS",
        "small": "S",
        "medium": "M",
        "large": "L",
        "extra large": "XL",
        "extra extra large": "XXL",
    }
    candidate = long_forms.get(cleaned.casefold().replace("-", " "))
    if candidate and candidate.casefold() in by_fold:
        return by_fold[candidate.casefold()]
    return None
