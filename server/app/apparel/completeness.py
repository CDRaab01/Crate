"""What a garment archive is still missing — the archive-first workflow's safety net.

Two questions, deliberately separate:

* `missing_for_listing` — everything eBay will want when the keyset finally arrives. Some
  of it (style, color) can be re-derived from the stored photos at listing time, so a gap
  here is a chore, not a loss.
* `missing_hand_only` — the subset that exists ONLY on the physical garment: the tag
  (brand, size, size type, material, department) and the tape measure. Once the shirt is
  folded into a bin, these cost an unboxing to recover. This is the list worth nagging
  about at capture time, and the reason it is computed rather than left to the eye.

Pure by design (CLAUDE.md §9: "clients display, never compute") — takes a plain mapping so
it is table-testable without a DB, with `attrs_from_item` as the ORM adapter.
"""

from collections.abc import Mapping

# eBay's clothing categories want these as item specifics. Order is display order.
LISTING_FIELDS = (
    "brand",
    "size",
    "size_type",
    "department",
    "color",
    "material",
    "style",
    "condition",
)

# The subset that cannot be recovered from photos once the garment is packed away. Every
# one of these is read off a tag or measured with a tape — a stored photo of a folded shirt
# will not give them back. `measurements` is the JSON blob, present/absent as a whole.
HAND_ONLY_FIELDS = (
    "brand",
    "size",
    "size_type",
    "department",
    "material",
    "measurements",
)


def attrs_from_item(item) -> dict:
    """ORM adapter: the apparel-relevant slice of an Item as a plain dict."""
    return {
        "item_kind": item.item_kind,
        "brand": item.brand,
        "size": item.size,
        "size_type": item.size_type,
        "department": item.department,
        "color": item.color,
        "material": item.material,
        "style": item.style,
        "condition": item.condition,
        "measurements": item.measurements_in,
    }


def _blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, dict):
        return not value
    return False


def missing_for_listing(attrs: Mapping[str, object]) -> list[str]:
    """Listing-relevant fields that are still empty, in display order.

    Non-clothing items return [] — the general-goods path (a lure, a tool) has its own
    much looser specifics, and flagging "size" on a fishing lure would train the user to
    ignore the whole indicator.
    """
    if attrs.get("item_kind") != "clothing":
        return []
    return [field for field in LISTING_FIELDS if _blank(attrs.get(field))]


def missing_hand_only(attrs: Mapping[str, object]) -> list[str]:
    """The urgent subset: gaps that require the physical garment back in hand.

    Always a subset of `missing_for_listing` for clothing, so the UI can show one list and
    mark these as the ones worth walking back to the bin for.
    """
    if attrs.get("item_kind") != "clothing":
        return []
    return [field for field in HAND_ONLY_FIELDS if _blank(attrs.get(field))]
