import uuid

from app.database import AsyncSessionLocal
from app.models.user import User
from app.security import create_access_token, create_refresh_token


async def make_user() -> User:
    async with AsyncSessionLocal() as db:
        user = User(name="Refresh Tester", email=f"refresh_{uuid.uuid4().hex[:8]}@example.com")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def test_refresh_rotates_tokens(client):
    user = await make_user()
    r = await client.post(
        "/auth/refresh", json={"refresh_token": create_refresh_token(str(user.id))}
    )
    assert r.status_code == 200
    body = r.json()
    # The new access token actually works.
    me = await client.get("/users/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["id"] == str(user.id)


async def test_access_token_rejected_as_refresh(client):
    user = await make_user()
    r = await client.post(
        "/auth/refresh", json={"refresh_token": create_access_token(str(user.id))}
    )
    assert r.status_code == 401


async def test_garbage_refresh_rejected(client):
    r = await client.post("/auth/refresh", json={"refresh_token": "junk"})
    assert r.status_code == 401


async def test_users_me_requires_auth(client):
    r = await client.get("/users/me")
    assert r.status_code == 401
