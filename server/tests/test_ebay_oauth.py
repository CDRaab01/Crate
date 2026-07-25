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
    now = datetime.datetime.now(datetime.timezone.utc)
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
    now = datetime.datetime.now(datetime.timezone.utc)
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
