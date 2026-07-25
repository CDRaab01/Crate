"""Browse API client against httpx.MockTransport — token flow, condition filters,
response parsing. eBay is ALWAYS mocked in CI (CLAUDE.md §8)."""

import json
from decimal import Decimal

import httpx
import pytest

from app.config import settings
from app.pricing import browse

SEARCH_BODY = {
    "itemSummaries": [
        {
            "title": "Rapala F11 silver",
            "price": {"value": "12.99", "currency": "USD"},
            "condition": "Used",
            "itemWebUrl": "https://ebay.com/itm/1",
        },
        {
            "title": "Rapala F11 new in box",
            "price": {"value": "19.99", "currency": "USD"},
            "condition": "New",
            "itemWebUrl": "https://ebay.com/itm/2",
        },
        {"title": "broken row, no price"},
    ]
}


@pytest.fixture(autouse=True)
def ebay_configured(monkeypatch):
    monkeypatch.setattr(settings, "ebay_client_id", "test-id")
    monkeypatch.setattr(settings, "ebay_client_secret", "test-secret")
    monkeypatch.setattr(settings, "ebay_environment", "sandbox")
    browse.reset_token_cache()
    yield
    browse.reset_token_cache()


def mock_client(recorder: dict) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/identity/v1/oauth2/token"):
            recorder["token_auth"] = request.headers.get("authorization", "")
            recorder["token_calls"] = recorder.get("token_calls", 0) + 1
            return httpx.Response(200, json={"access_token": "app-token", "expires_in": 7200})
        recorder["search_url"] = str(request.url)
        recorder["search_auth"] = request.headers.get("authorization", "")
        recorder["marketplace"] = request.headers.get("x-ebay-c-marketplace-id", "")
        return httpx.Response(200, json=SEARCH_BODY)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_search_parses_comps_and_skips_broken_rows():
    rec: dict = {}
    async with mock_client(rec) as client:
        comps = await browse.search_active_comps("rapala f11", "good", client=client)
    assert [c.price for c in comps] == [Decimal("12.99"), Decimal("19.99")]
    assert comps[0].url == "https://ebay.com/itm/1"
    # Token flow: Basic auth on the token call, Bearer on the search.
    assert rec["token_auth"].startswith("Basic ")
    assert rec["search_auth"] == "Bearer app-token"
    assert rec["marketplace"] == "EBAY_US"
    # Sandbox host + fixed-price + the good-condition bucket.
    assert "api.sandbox.ebay.com" in rec["search_url"]
    assert "FIXED_PRICE" in rec["search_url"]
    assert "conditionIds" in rec["search_url"]


async def test_token_cached_across_searches():
    rec: dict = {}
    async with mock_client(rec) as client:
        await browse.search_active_comps("a", None, client=client)
        await browse.search_active_comps("b", None, client=client)
    assert rec["token_calls"] == 1


async def test_unknown_condition_omits_the_filter():
    rec: dict = {}
    async with mock_client(rec) as client:
        await browse.search_active_comps("a", None, client=client)
    assert "conditionIds" not in rec["search_url"]


def test_configured_flag(monkeypatch):
    assert browse.configured()
    monkeypatch.setattr(settings, "ebay_client_id", None)
    assert not browse.configured()


async def test_comps_endpoint_503_when_unconfigured(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "ebay_client_id", None)
    monkeypatch.setattr(settings, "ebay_client_secret", None)
    # Any item id works — config is checked before ownership.
    r = await auth_client.get("/items/00000000-0000-0000-0000-000000000000/comps")
    assert r.status_code == 503


async def test_pipeline_prices_draft_when_configured(auth_client, monkeypatch, tmp_path):
    """End-to-end: scan -> identify -> priced draft, with Browse mocked at the transport."""
    from app.services import scan_pipeline
    from app.services.ai.identify_prompts import IdentifyDraft

    monkeypatch.setattr(settings, "photos_dir", str(tmp_path / "photos"))
    monkeypatch.setattr(scan_pipeline, "clean_photo", lambda b: b)

    async def fake_identify(urls, client=None):
        return IdentifyDraft(title="Rapala F11", brand="Rapala", model="F11", confidence="high")

    monkeypatch.setattr(scan_pipeline, "identify_item", fake_identify)

    rec: dict = {}

    async def fake_price_search(query, condition, limit=50, client=None):
        rec["query"] = query
        body = json.loads(json.dumps(SEARCH_BODY))
        return [
            browse.Comp(
                title=s["title"],
                price=Decimal(s["price"]["value"]),
                condition=s.get("condition"),
                url=s.get("itemWebUrl"),
            )
            for s in body["itemSummaries"]
            if "price" in s
        ]

    import app.pricing.service as pricing_service

    monkeypatch.setattr(pricing_service.browse, "search_active_comps", fake_price_search)

    import asyncio

    r = await auth_client.post(
        "/items/scan", files=[("photos", ("p.png", b"\x89PNGxx", "image/png"))]
    )
    item_id = r.json()["id"]
    for _ in range(50):
        body = (await auth_client.get(f"/items/{item_id}")).json()
        if body["processed_at"] is not None:
            break
        await asyncio.sleep(0.05)

    assert rec["query"] == "Rapala F11"  # brand+model beats title as the query
    # patient = median(12.99, 19.99) = 16.49; quick = min(12.99*0.95, patient) = 12.34
    assert body["patient_price"] == "16.49"
    assert body["quick_sale_price"] == "12.34"
