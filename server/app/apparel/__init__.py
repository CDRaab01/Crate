"""Apparel attributes + archive completeness — pure, table-tested (CLAUDE.md §4/§9 style).

Exists because Crate's archive-first workflow (photograph a wardrobe now, list it when the
eBay keyset arrives) has one failure mode that no amount of later automation can repair:
size, material and measurements come off the garment's tag and a tape measure, not off a
photo. Box the shirt without them and the only way back is unboxing it.

So the pipeline records what it can see, refuses to guess what it can't, and this module
reports exactly what a human still has to supply while the garment is still in hand.
"""

from app.apparel.attributes import (
    DEPARTMENTS,
    FITS,
    MEASUREMENT_KEYS,
    SIZE_TYPES,
    SLEEVE_LENGTHS,
    normalize_enum,
    normalize_measurements,
)
from app.apparel.completeness import (
    HAND_ONLY_FIELDS,
    LISTING_FIELDS,
    attrs_from_item,
    missing_for_listing,
    missing_hand_only,
)

__all__ = [
    "DEPARTMENTS",
    "FITS",
    "HAND_ONLY_FIELDS",
    "LISTING_FIELDS",
    "MEASUREMENT_KEYS",
    "SIZE_TYPES",
    "SLEEVE_LENGTHS",
    "attrs_from_item",
    "missing_for_listing",
    "missing_hand_only",
    "normalize_enum",
    "normalize_measurements",
]
