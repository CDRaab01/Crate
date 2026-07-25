"""Suite SSO tests — self-contained RS256 keypair, JWKS fetch faked, no network."""

import time
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk, jwt
from sqlalchemy import func, select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.user_settings import UserSettings

KID = "test-kid"
ISSUER = "https://id.test"
AUDIENCE = "suite"

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_private_pem = _private_key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
_public_pem = (
    _private_key.public_key()
    .public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode()
)
_jwk = jwk.construct(_public_pem, algorithm="RS256").to_dict()
_jwk["kid"] = KID
JWKS = {"keys": [_jwk]}


def mint(email: str | None, *, issuer: str = ISSUER, audience: str = AUDIENCE, name=None) -> str:
    claims = {
        "sub": str(uuid.uuid4()),
        "iss": issuer,
        "aud": audience,
        "exp": int(time.time()) + 300,
    }
    if email is not None:
        claims["email"] = email
    if name is not None:
        claims["name"] = name
    return jwt.encode(claims, _private_pem, algorithm="RS256", headers={"kid": KID})


@pytest.fixture
def suite_enabled(monkeypatch):
    monkeypatch.setattr(settings, "suite_jwks_url", "https://id.test/jwks.json")
    monkeypatch.setattr(settings, "suite_issuer", ISSUER)
    monkeypatch.setattr(settings, "suite_audience", AUDIENCE)

    async def fake_fetch_jwks(*, force: bool = False) -> dict:
        return JWKS

    import app.services.suite_auth as sa_mod

    monkeypatch.setattr(sa_mod, "_fetch_jwks", fake_fetch_jwks)


async def test_disabled_by_default_returns_404(client, monkeypatch):
    monkeypatch.setattr(settings, "suite_jwks_url", None)
    monkeypatch.setattr(settings, "suite_issuer", None)
    r = await client.post("/auth/suite", json={"suite_token": "anything"})
    assert r.status_code == 404


async def test_new_email_creates_user_and_settings(client, suite_enabled):
    email = f"sso_{uuid.uuid4().hex[:8]}@example.com"
    r = await client.post("/auth/suite", json={"suite_token": mint(email, name="Box Seller")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"] and body["refresh_token"]

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        assert user.name == "Box Seller"
        # The per-user settings row is seeded at first login so the drop scheduler and
        # shipping preference always have values to read.
        settings_row = (
            await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
        ).scalar_one()
        assert settings_row.drop_interval_days == 14

    # Second login reuses the account (no duplicate).
    r2 = await client.post("/auth/suite", json={"suite_token": mint(email)})
    assert r2.status_code == 200
    async with AsyncSessionLocal() as db:
        count = (
            await db.execute(select(func.count()).select_from(User).where(User.email == email))
        ).scalar_one()
        assert count == 1


async def test_session_token_works_on_users_me(client, suite_enabled):
    email = f"sso_{uuid.uuid4().hex[:8]}@example.com"
    r = await client.post("/auth/suite", json={"suite_token": mint(email)})
    token = r.json()["access_token"]
    me = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == email


async def test_wrong_issuer_rejected(client, suite_enabled):
    r = await client.post(
        "/auth/suite",
        json={"suite_token": mint("x@example.com", issuer="https://evil.test")},
    )
    assert r.status_code == 401


async def test_wrong_audience_rejected(client, suite_enabled):
    r = await client.post(
        "/auth/suite",
        json={"suite_token": mint("x@example.com", audience="cross-app")},
    )
    assert r.status_code == 401


async def test_token_without_email_rejected(client, suite_enabled):
    r = await client.post("/auth/suite", json={"suite_token": mint(None)})
    assert r.status_code == 401


async def test_garbage_token_rejected(client, suite_enabled):
    r = await client.post("/auth/suite", json={"suite_token": "not-a-jwt"})
    assert r.status_code == 401
