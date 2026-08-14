"""Controlled vocabularies + normalizers for apparel item specifics.

The vocabularies mirror eBay's clothing item-specific values closely enough that Phase 5
posting can map them straight across, but they are OUR enums: the API is not connected yet
and guessing at eBay's exact strings now would bake in an unverifiable assumption. Mapping
to eBay's aspect values happens in `services/ebay/sell.py` when a keyset exists.

Free-text fields (size, color, material, style) are deliberately NOT enumerated — real tags
say "Heather Grey", "60% cotton / 40% poly", "M/L". Constraining them would lose data that
a human read off the garment, which is the one thing this workflow cannot re-derive later.
"""

import re

# Sized enums: these are the fields where a controlled value is genuinely knowable from the
# tag or the garment, and where free text would fragment the registry.
DEPARTMENTS = ("mens", "womens", "unisex", "boys", "girls")
SIZE_TYPES = ("regular", "petite", "plus", "big_tall", "juniors", "maternity")
SLEEVE_LENGTHS = ("sleeveless", "short", "three_quarter", "long")
FITS = ("slim", "regular", "relaxed", "oversized")

# Tape-measure fields, inches, garment laid flat. Tops use chest/length/sleeve/shoulder;
# bottoms use waist/inseam/rise. One union keeps the JSON shape stable across garment types
# — an absent key just means "not measured", never "zero".
MEASUREMENT_KEYS = ("chest", "length", "sleeve", "shoulder", "waist", "inseam", "rise")

# A garment measurement above this is a typo or a unit mix-up (cm entered as inches), not a
# real tape reading — 90" is longer than any wearable single garment dimension.
_MAX_MEASUREMENT_IN = 90.0


def normalize_enum(value: object, allowed: tuple[str, ...]) -> str | None:
    """Casefold + snake-case a vocabulary value, or None when it isn't in `allowed`.

    Forgiving on shape ("Big & Tall", "three-quarter", "Mens") because vision output and
    hand entry both drift; strict on membership, because an unrecognized enum silently
    stored is a listing that fails validation months later at post time.
    """
    if value is None:
        return None
    text = re.sub(r"[^a-z0-9]+", "_", str(value).strip().casefold()).strip("_")
    if not text:
        return None
    if text in allowed:
        return text
    # Common tag phrasings that don't survive the mechanical squash above.
    aliases = {
        "men": "mens",
        "man": "mens",
        "male": "mens",
        "women": "womens",
        "woman": "womens",
        "female": "womens",
        "big_and_tall": "big_tall",
        "big_tall_": "big_tall",
        "3_4": "three_quarter",
        "three_quarters": "three_quarter",
        "quarter": "three_quarter",
        "short_sleeve": "short",
        "long_sleeve": "long",
        "loose": "relaxed",
        "standard": "regular",
    }
    resolved = aliases.get(text)
    return resolved if resolved in allowed else None


def normalize_measurements(value: object) -> dict | None:
    """Coerce a measurements payload to {key: float inches} over MEASUREMENT_KEYS.

    Unknown keys are dropped, non-numeric and out-of-range values are dropped, and an empty
    result is None — "no measurements" must read as absent, not as an empty dict that looks
    like someone already did the work.
    """
    if not isinstance(value, dict):
        return None
    out: dict[str, float] = {}
    for key in MEASUREMENT_KEYS:
        raw = value.get(key)
        if raw is None:
            continue
        try:
            number = float(str(raw).strip())
        except (TypeError, ValueError):
            continue
        if 0 < number <= _MAX_MEASUREMENT_IN:
            out[key] = round(number, 2)
    return out or None
