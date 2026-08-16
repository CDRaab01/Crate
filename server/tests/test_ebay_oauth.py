"""Seller OAuth: connect/callback state flow, Fernet-encrypted persistence, refresh."""

import datetime

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.ebay_credentials import EbayCredentials
from app.services.ebay import oauth

FERNET_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def ebay_configured(monkeypatch):
    monkeypatch.setattr(settings, "ebay_client_id", "test-id")
    monkeypatch.setattr(settings, "ebay_client_secret", "test-secret")
    monkeypatch.setattr(settings, "ebay_ru_name", "Test-RuName")
    monkeypatch.setattr(settings, "fernet_key", FERNET_KEY)
    monkeypatch.setattr(settings, "ebay_environment", "sandbox")


def token_transport(recorder: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        recorder["body"] = request.content.decode()
        recorder["auth"] = request.headers.get("authorization", "")
        return httpx.Response(
            200,
            json={
                "access_token": "user-access",
                "refresh_token": "user-refresh",
                "expires_in": 7200,
                "refresh_token_expires_in": 47304000,
            },
        )

    return httpx.MockTransport(handler)


async def test_connect_returns_authorize_url_and_callback_stores_encrypted(
    auth_client, monkeypatch
):
    r = await auth_client.get("/ebay/connect")
    assert r.status_code == 200, r.text
    url = r.json()["authorize_url"]
    assert url.startswith("https://auth.sandbox.ebay.com/oauth2/authorize?")
    assert "Test-RuName" in url
    state = httpx.URL(url).params["state"]

    rec: dict = {}

    async def fake_token_request(data, client=None):
        rec["data"] = data
        return {
            "access_token": "user-access",
            "refresh_token": "user-refresh",
            "expires_in": 7200,
            "refresh_token_expires_in": 47304000,
        }

    monkeypatch.setattr(oauth, "_token_request", fake_token_request)

    r = await auth_client.get("/ebay/callback", params={"code": "the-code", "state": state})
    assert r.status_code == 200
    assert "connected" in r.text.lower()
    assert rec["data"]["grant_type"] == "authorization_code"

    async with AsyncSessionLocal() as db:
        creds = (
            await db.execute(
                select(EbayCredentials).where(EbayCredentials.user_id == auth_client.user_id)
            )
        ).scalar_one()
        # Encrypted at rest — never the raw token — and decryptable back.
        assert creds.access_token_enc != "user-access"
        assert oauth.decrypt(creds.access_token_enc) == "user-access"
        assert oauth.decrypt(creds.refresh_token_enc) == "user-refresh"
        assert creds.environment == "sandbox"

    # Status endpoint reflects the connection.
    r = await auth_client.get("/ebay/status")
    body = r.json()
    assert body["connected"] is True and body["configured"] is True

    # Disconnect wipes it.
    r = await auth_client.delete("/ebay/connection")
    assert r.status_code == 204
    assert (await auth_client.get("/ebay/status")).json()["connected"] is False


async def test_callback_rejects_unknown_state(client):
    r = await client.get("/ebay/callback", params={"code": "x", "state": "bogus"})
    assert r.status_code == 401


async def test_connect_503_when_unconfigured(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "fernet_key", None)
    r = await auth_client.get("/ebay/connect")
    assert r.status_code == 503


async def test_user_token_refreshes_when_expiring(auth_client, monkeypatch):
    now = datetime.datetime.now(datetime.UTC)
    async with AsyncSessionLocal() as db:
        db.add(
            EbayCredentials(
                user_id=auth_client.user_id,
                access_token_enc=oauth.encrypt("stale-access"),
                refresh_token_enc=oauth.encrypt("user-refresh"),
                expires_at=now + datetime.timedelta(minutes=1),  # inside the 5-min window
                refresh_expires_at=now + datetime.timedelta(days=400),
                environment="sandbox",
            )
        )
        await db.commit()

    rec: dict = {}
    async with httpx.AsyncClient(transport=token_transport(rec)) as http:
        async with AsyncSessionLocal() as db:
            token = await oauth.user_token(db, auth_client.user_id, client=http)
    assert token == "user-access"
    assert "grant_type=refresh_token" in rec["body"]
    assert rec["auth"].startswith("Basic ")

    # The refreshed token was re-persisted (encrypted).
    async with AsyncSessionLocal() as db:
        creds = (
            await db.execute(
                select(EbayCredentials).where(EbayCredentials.user_id == auth_client.user_id)
            )
        ).scalar_one()
        assert oauth.decrypt(creds.access_token_enc) == "user-access"


async def test_user_token_409_when_never_connected(auth_client):
    async with AsyncSessionLocal() as db:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as e:
            await oauth.user_token(db, auth_client.user_id)
        assert e.value.status_code == 409


async def test_user_token_409_when_refresh_expired(auth_client):
    now = datetime.datetime.now(datetime.UTC)
    async with AsyncSessionLocal() as db:
        db.add(
            EbayCredentials(
                user_id=auth_client.user_id,
                access_token_enc=oauth.encrypt("stale"),
                refresh_token_enc=oauth.encrypt("dead"),
                expires_at=now - datetime.timedelta(hours=1),
                refresh_expires_at=now - datetime.timedelta(days=1),
                environment="sandbox",
            )
        )
        await db.commit()

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as e:
            await oauth.user_token(db, auth_client.user_id)
        assert e.value.status_code == 409
        assert "reconnect" in e.value.detail.lower()


# ── the 2026-08-15 consent audit: gaps that let six bare redirects go undiagnosed ─────


async def test_bare_callback_renders_a_human_page_not_json(client):
    """eBay legitimately redirects here with NO query at all (declined consent, or the
    already-granted no-reprompt path). That lands in a person's browser tab; the raw
    `{"detail":"Missing code/state"}` it used to show read as a server bug and cost a
    debugging session. It must be an HTML explanation now."""
    r = await client.get("/ebay/callback")
    assert r.status_code == 400
    assert r.headers["content-type"].startswith("text/html")
    assert "without an authorization code" in r.text
    assert "ebay_manual_consent" in r.text  # points at the escape hatch
    assert "Missing code/state" not in r.text


async def test_authorize_url_forces_reprompt_and_carries_base_scope(auth_client):
    """Guardrail strings. Without prompt=login, eBay treats an already-granted keyset as
    'nothing to ask' and redirects WITHOUT a code — the audit's six bare callbacks. The
    base api_scope is the one scope every keyset holds; eBay's own consent URLs lead with
    it. A silent edit dropping either reintroduces an undiagnosable consent failure."""
    url = (await auth_client.get("/ebay/connect")).json()["authorize_url"]
    params = httpx.URL(url).params
    assert params["prompt"] == "login"
    scopes = params["scope"].split(" ")
    assert "https://api.ebay.com/oauth/api_scope" in scopes
    assert scopes[0] == "https://api.ebay.com/oauth/api_scope", "base scope leads the list"
    assert "https://api.ebay.com/oauth/api_scope/sell.inventory" in scopes
    assert "https://api.ebay.com/oauth/api_scope/sell.fulfillment" in scopes


async def test_realistically_shaped_code_round_trips(auth_client, monkeypatch):
    """eBay codes are not 'the-code': they are v^1.1#...-shaped blobs that arrive
    percent-encoded, alongside expires_in and isAuthSuccessful params nothing here should
    choke on. Documents the real redirect shape so the next reader knows it."""
    url = (await auth_client.get("/ebay/connect")).json()["authorize_url"]
    state = httpx.URL(url).params["state"]

    rec: dict = {}

    async def fake_token_request(data, client=None):
        rec["data"] = data
        return {
            "access_token": "user-access",
            "refresh_token": "user-refresh",
            "expires_in": 7200,
            "refresh_token_expires_in": 47304000,
        }

    monkeypatch.setattr(oauth, "_token_request", fake_token_request)

    real_shaped = "v^1.1#i^1#f^0#r^1#p^3#I^3#t^Ul4xMF8xOkFCQ0RFRj09"
    r = await auth_client.get(
        "/ebay/callback",
        params={
            "code": real_shaped,
            "state": state,
            "expires_in": "299",
            "isAuthSuccessful": "true",
        },
    )
    assert r.status_code == 200, r.text
    # The code must reach the token exchange VERBATIM — FastAPI decodes the query; a
    # second decode (or none, from a manual caller) is a silent invalid_grant.
    assert rec["data"]["code"] == real_shaped


def _load_manual_consent_module():
    """scripts/ is not a package; load the module by path (it guards its app imports
    behind sys.path juggling, so importing it here exercises the same path the container
    run does)."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "ebay_manual_consent.py"
    spec = importlib.util.spec_from_file_location("ebay_manual_consent", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "raw,expected",
    [
        # The whole success-page URL pasted straight from the address bar (encoded code).
        (
            (
                "https://auth.sandbox.ebay.com/oauth2/ThirdPartyAuthSucessFailure"
                "?isAuthSuccessful=true&code=v%5E1.1%23i%5E1%23f%5E0&expires_in=299"
            ),
            "v^1.1#i^1#f^0",
        ),
        # Bare code, still percent-encoded.
        ("v%5E1.1%23i%5E1%23f%5E0", "v^1.1#i^1#f^0"),
        # Bare code already decoded — a '#' means decoded; must NOT be unquoted again.
        ("v^1.1#i^1#f^0", "v^1.1#i^1#f^0"),
        # Whitespace from a sloppy copy.
        ("  v^1.1#i^1#f^0  ", "v^1.1#i^1#f^0"),
    ],
)
def test_manual_consent_extract_code(raw, expected):
    """The manual path's one piece of real logic: URL vs bare, encoded vs not. Getting the
    decode-or-not call wrong is a silent invalid_grant at the token endpoint."""
    module = _load_manual_consent_module()
    assert module.extract_code(raw) == expected


def test_manual_consent_rejects_url_without_code():
    module = _load_manual_consent_module()
    with pytest.raises(SystemExit):
        module.extract_code("https://example.com/callback?error=access_denied")
