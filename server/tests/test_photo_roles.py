"""Photo roles: the listing order they imply, and the archive gap a missing tag shot leaves.

Table-driven per CLAUDE.md §8. The ordering half is worth real tests because it is the one
part of the roles feature that changes what a BUYER sees — eBay uses the first uploaded
photo as the listing's gallery image — and because eBay is always mocked in CI, it is also
the one part CI can verify end to end.
"""

import pytest

from app.apparel import PHOTO_ROLES, missing_photo_roles, normalize_enum, photo_role_rank
from app.apparel.attributes import _LISTING_ORDER


def test_listing_order_covers_every_role():
    """Adding a role without deciding where it appears in a listing should fail here.

    photo_role_rank falls back to the unknown slot for anything it doesn't recognise, so a
    role missing from _LISTING_ORDER would silently sort as unknown instead of raising —
    the sort would keep working and quietly put the new role in the wrong place.
    """
    assert set(PHOTO_ROLES) <= set(_LISTING_ORDER)
    assert None in _LISTING_ORDER, "the unknown slot must be explicit, not implied"


@pytest.mark.parametrize(
    "role,expected_rank_of",
    [
        ("front", "front"),
        ("back", "back"),
        ("detail", "detail"),
        ("tag", "tag"),
        (None, None),
        # A role from a future client version must not be able to break posting a listing.
        ("hero", None),
        ("", None),
    ],
)
def test_rank_places_known_and_unknown_roles(role, expected_rank_of):
    assert photo_role_rank(role) == photo_role_rank(expected_rank_of)


def test_tag_never_becomes_the_hero_image():
    """The reason this feature exists: shoot the tag first and it used to lead the listing."""
    shot_order = [(0, "tag"), (1, "front"), (2, "back")]
    ordered = sorted(shot_order, key=lambda p: photo_role_rank(p[1]))
    assert [role for _, role in ordered] == ["front", "back", "tag"]


def test_tag_is_last_but_still_included():
    """Included deliberately — a care label is real size proof buyers want. Just not first."""
    shot_order = [(0, "tag"), (1, "front"), (2, "detail")]
    ordered = sorted(shot_order, key=lambda p: photo_role_rank(p[1]))
    assert len(ordered) == 3
    assert ordered[-1][1] == "tag"


def test_roleless_photos_keep_their_original_order():
    """Backward compatibility is structural: every pre-roles photo gets the same rank, and
    Python's sort is stable, so an old item's listing is byte-identical to before."""
    original = [(order, None) for order in range(5)]
    ordered = sorted(original, key=lambda p: photo_role_rank(p[1]))
    assert [order for order, _ in ordered] == [0, 1, 2, 3, 4]


def test_unknown_outranks_tag_but_yields_to_known_roles():
    """An unlabelled photo is more likely a garment shot than a label."""
    mixed = [(0, "tag"), (1, None), (2, "front")]
    ordered = sorted(mixed, key=lambda p: photo_role_rank(p[1]))
    assert [role for _, role in ordered] == ["front", None, "tag"]


@pytest.mark.parametrize(
    "raw,expected",
    [("tag", "tag"), ("Tag", "tag"), ("  FRONT  ", "front"), ("hero", None), (None, None)],
)
def test_roles_normalize_like_every_other_vocabulary(raw, expected):
    assert normalize_enum(raw, PHOTO_ROLES) == expected


@pytest.mark.parametrize(
    "roles,item_kind,expected",
    [
        # The gap that matters: a garment with no tag shot.
        ([None, None], "clothing", ["tag_photo"]),
        (["front", "back"], "clothing", ["tag_photo"]),
        (["front", "tag"], "clothing", []),
        (["tag"], "clothing", []),
        ([], "clothing", ["tag_photo"]),
        # Non-clothing short-circuits, same as the other completeness checks — nagging about
        # a fishing lure's missing tag would train the user to ignore the indicator.
        ([None], "general", []),
        (["front"], "general", []),
        ([], None, []),
    ],
)
def test_missing_photo_roles(roles, item_kind, expected):
    assert missing_photo_roles(roles, item_kind) == expected
