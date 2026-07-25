from app.main import APP_VERSION


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_version_reports_suite_contract(client):
    r = await client.get("/version")
    assert r.status_code == 200
    body = r.json()
    # The suite contract Dragonfly and the deploy gate rely on.
    assert set(body) == {"name", "version", "commit", "built_at"}
    assert body["name"] == "Crate API"
    assert body["version"] == APP_VERSION
