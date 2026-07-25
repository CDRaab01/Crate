from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App configuration from environment variables (and server/.env locally).

    Suite rule: required non-secret config is pinned in docker-compose.yml's `environment:`
    block (Compose does not re-read a changed env_file on recreate); secrets live in
    server/.env only. A `None` credential/URL disables its feature (404/503) rather than
    crashing — every integration must degrade honestly.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Test-suite setting: pooled asyncpg connections bind to the creating event loop, which
    # breaks under pytest-asyncio's per-test loops. See app.database.
    db_nullpool: bool = False

    # Deploy hardening (Crate is tailnet-only; TRUST_PROXY stays off unless a proxy fronts it).
    trust_proxy: bool = False
    hsts_enabled: bool = False
    docs_enabled: bool = True

    # Deploy stamp surfaced by GET /version (exported by deploy/redeploy.* before compose up).
    git_sha: str = "unknown"
    built_at: str = "unknown"

    # Suite SSO (Magpie SSO-only pattern): unset => POST /auth/suite is disabled (404).
    # Crate has no password auth at all, so without these the app has no login path — the two
    # vars are pinned in compose `environment:` in production.
    suite_jwks_url: str | None = None
    suite_issuer: str | None = None
    suite_audience: str = "suite"

    external_timeout_seconds: float = 8.0


settings = Settings()
