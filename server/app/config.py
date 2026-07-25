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

    # LM Studio vision (item identification + condition + weight/dims estimate). The base URL
    # and model are pinned in compose `environment:` in production — inside the container
    # localhost is the container, so the default below only works for bare-metal local dev.
    lm_studio_base_url: str = "http://localhost:1234/v1"
    lm_studio_vision_model: str = "google/gemma-4-e4b"
    lm_studio_timeout: float = 60.0

    # Item photos: binaries on a volume, paths in the DB. 8 MB cap matches the client's
    # ≤1600px JPEG downscale contract.
    photos_dir: str = "/data/photos"
    photo_max_bytes: int = 8 * 1024 * 1024

    # rembg background removal (local U2-Net, CPU). Disabled ⇒ Pillow-only cleanup — the
    # pipeline degrades, never blocks on it.
    background_removal_enabled: bool = True

    # eBay (always mocked in CI; keyset in server/.env when the developer account exists).
    # Unset client id/secret ⇒ pricing is silently skipped in the pipeline and /comps 503s.
    ebay_client_id: str | None = None
    ebay_client_secret: str | None = None
    ebay_environment: str = "sandbox"  # sandbox | production
    ebay_marketplace_id: str = "EBAY_US"


settings = Settings()
