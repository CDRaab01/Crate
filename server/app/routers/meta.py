"""Controlled vocabularies for the client's review-stage dropdowns.

The vocabularies are defined once in `apparel/attributes.py` and served from here rather
than duplicated in Kotlin: CLAUDE.md §9 is "clients display, never compute", and a hardcoded
copy on the phone would silently drift the moment a value is added — producing a draft the
server then rejects with a 422 the user can do nothing about.

Display labels are computed here for the same reason. `big_tall` is the wire value the API
validates; "Big & Tall" is what a human picks from a menu, and deriving that on the client
would mean two places to fix when a label reads badly.
"""

from fastapi import APIRouter

from app.apparel import DEPARTMENTS, FITS, SIZE_TYPES, SLEEVE_LENGTHS
from app.models.item import ITEM_CONDITIONS

router = APIRouter(prefix="/meta", tags=["meta"])

# Labels that title-casing gets wrong. Everything else derives from the enum value, so a new
# vocabulary entry shows up in the dropdown without a code change here.
_LABEL_OVERRIDES = {
    "big_tall": "Big & Tall",
    "three_quarter": "3/4 Sleeve",
    "mens": "Men's",
    "womens": "Women's",
    "like_new": "Like New",
}


def _label(value: str) -> str:
    return _LABEL_OVERRIDES.get(value, value.replace("_", " ").title())


def _vocabulary(values: tuple[str, ...]) -> list[dict[str, str]]:
    return [{"value": v, "label": _label(v)} for v in values]


@router.get("/vocabularies")
async def vocabularies() -> dict[str, list[dict[str, str]]]:
    """Every controlled vocabulary the review screen offers as a dropdown.

    Unauthenticated on purpose: this is static reference data with nothing user-specific in
    it, and the client needs it to render a draft before any item is loaded.
    """
    return {
        "departments": _vocabulary(DEPARTMENTS),
        "size_types": _vocabulary(SIZE_TYPES),
        "sleeve_lengths": _vocabulary(SLEEVE_LENGTHS),
        "fits": _vocabulary(FITS),
        "conditions": _vocabulary(ITEM_CONDITIONS),
    }
