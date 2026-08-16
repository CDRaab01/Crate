"""Review-stage dropdown support: vocabularies + eBay category suggestions.

Both exist so the human picks values the server already validates, instead of the client
guessing them or the AI inventing them.
"""

import httpx
import pytest

from app.apparel import DEPARTMENTS, SIZE_TYPES
from app.models.item import Item
from app.services.ebay import taxonomy

pytestmark = pytest.mark.asyncio


async def test_vocabularies_cover_every_server_side_enum(client):
    """A value the server accepts but the dropdown never offers is unreachable in the app."""
    resp = await client.get("/meta/vocabularies")
    assert resp.status_code == 200
    body = resp.json()
    assert {v["value"] for v in body["departments"]} == set(DEPARTMENTS)
    assert {v["value"] for v in body["size_types"]} == set(SIZE_TYPES)


async def test_vocabularies_label_the_values_a_human_has_to_read(client):
    """`big_tall` is the wire value; nobody picks that from a menu."""
    body = (await client.get("/meta/vocabularies")).json()
    labels = {v["value"]: v["label"] for v in body["size_types"]}
    assert labels["big_tall"] == "Big & Tall"
    assert labels["regular"] == "Regular"
    sleeves = {v["value"]: v["label"] for v in body["sleeve_lengths"]}
    assert sleeves["three_quarter"] == "3/4 Sleeve"


def test_query_prefers_the_title_but_folds_in_missing_attributes():
    item = Item(title="Men's Polo Shirt", brand="Lands End", style="Polo", department="mens")
    query = taxonomy.query_for(item)
    assert query.startswith("Men's Polo Shirt")
    assert "Lands" in query
    # "Polo" appears in both title and style — it must not be sent twice.
    assert query.split().count("Polo") == 1


def test_query_is_empty_when_there_is_nothing_to_match_on():
    """An unidentified draft must not fire a pointless eBay call."""
    assert taxonomy.query_for(Item(title=None, brand=None, style=None, department=None)) == ""


async def test_suggestions_flatten_ebay_ancestry_into_a_breadcrumb():
    """Two categories can share a leaf name; the path is what disambiguates them."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2/token" in str(request.url):
            return httpx.Response(200, json={"access_token": "app-tok", "expires_in": 7200})
        if "get_default_category_tree_id" in str(request.url):
            return httpx.Response(200, json={"categoryTreeId": "0"})
        return httpx.Response(
            200,
            json={
                "categorySuggestions": [
                    {
                        "category": {"categoryId": "185101", "categoryName": "Polos"},
                        "categoryTreeNodeAncestors": [
                            {"categoryName": "Shirts"},
                            {"categoryName": "Men's Clothing"},
                            {"categoryName": "Men"},
                        ],
                    }
                ]
            },
        )

    item = Item(title="Men's Polo Shirt", brand="Lands End", style="Polo", department="mens")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        found = await taxonomy.suggest_categories(item, client=http)

    assert len(found) == 1
    assert found[0].category_id == "185101"
    assert found[0].path == "Men > Men's Clothing > Shirts"


async def test_suggestions_skip_entries_without_an_id():
    """A category with no id cannot be posted with — dropping it beats offering a dud."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2/token" in str(request.url):
            return httpx.Response(200, json={"access_token": "app-tok", "expires_in": 7200})
        if "get_default_category_tree_id" in str(request.url):
            return httpx.Response(200, json={"categoryTreeId": "0"})
        return httpx.Response(
            200,
            json={
                "categorySuggestions": [
                    {"category": {"categoryName": "Broken"}},
                    {"category": {"categoryId": "185101", "categoryName": "Polos"}},
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        found = await taxonomy.suggest_categories(Item(title="Polo"), client=http)

    assert [s.category_id for s in found] == ["185101"]


@pytest.mark.parametrize(
    "tag_text,expected",
    [
        ("S", "S"),  # already standard
        (" m ", "M"),  # whitespace and case
        ("Small", "S"),  # eBay's own documented normalization
        ("EXTRA LARGE", "XL"),
        ("extra-large", "XL"),
        # Genuinely ambiguous readings must NOT be resolved — a wrong size ships the wrong
        # garment, and the human is one dropdown away.
        ("M/L", None),
        ("EUR 30 / US 30 / CN 170/76A", None),
        ("別大", None),
        ("32x34", None),
        (None, None),
        ("", None),
    ],
)
def test_match_standard_size_resolves_only_the_unambiguous(tag_text, expected):
    permitted = ["XXS", "XS", "S", "M", "L", "XL", "XXL"]
    assert taxonomy.match_standard_size(tag_text, permitted) == expected


def test_match_standard_size_never_invents_a_value_the_category_forbids():
    """'Small' means nothing if this category does not publish 'S'."""
    assert taxonomy.match_standard_size("Small", ["Petite", "Regular"]) is None
    assert taxonomy.match_standard_size("S", []) is None


async def test_aspect_values_reads_the_live_constraint_not_a_hardcoded_list():
    """eBay is tightening size values over time; the SELECTION_ONLY flag has to come from
    them, or the day Size stops being free text we ship blocked listings."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2/token" in str(request.url):
            return httpx.Response(200, json={"access_token": "app-tok", "expires_in": 7200})
        if "get_default_category_tree_id" in str(request.url):
            return httpx.Response(200, json={"categoryTreeId": "0"})
        return httpx.Response(
            200,
            json={
                "aspects": [
                    {
                        "localizedAspectName": "Size",
                        "aspectConstraint": {
                            "aspectRequired": True,
                            "aspectMode": "SELECTION_ONLY",
                        },
                        "aspectValues": [
                            {"localizedValue": "S"},
                            {"localizedValue": "M"},
                            {"localizedValue": "L"},
                        ],
                    },
                    {
                        "localizedAspectName": "Pattern",
                        "aspectConstraint": {
                            "aspectRequired": False,
                            "aspectMode": "FREE_TEXT",
                        },
                        "aspectValues": [],
                    },
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        found = await taxonomy.aspect_values("185101", client=http)

    size = next(a for a in found if a.name == "Size")
    assert size.required is True
    assert size.selection_only is True
    assert size.values == ["S", "M", "L"]
    pattern = next(a for a in found if a.name == "Pattern")
    assert pattern.selection_only is False
