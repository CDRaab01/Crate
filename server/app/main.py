from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.extension import _rate_limit_exceeded_handler
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.config import settings
from app.limiter import limiter
from app.routers import (
    auth,
    ebay,
    items,
    messages,
    meta,
    shipping,
    suite_auth,
    templates,
    users,
)
from app.routers import (
    settings as settings_router,
)
from app.services import poller

# Single source for the human-facing version, reused by GET /version below.
APP_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The 15-min order/message poller (no-op until eBay is configured; interval 0 in CI).
    poller.start()
    yield
    poller.stop()


# Interactive docs are handy locally but an unnecessary surface on a deployment.
app = FastAPI(
    title="Crate API",
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": "Conflict with existing data"})


@app.exception_handler(DBAPIError)
async def dbapi_error_handler(request: Request, exc: DBAPIError) -> JSONResponse:
    # SQLSTATE class 22 = data exception (e.g. a NUL byte in text): the client sent something
    # the database can't store — a 422, not a 500.
    sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None) or ""
    if sqlstate.startswith("22"):
        return JSONResponse(status_code=422, content={"detail": "Invalid data"})
    raise exc


# Android talks Bearer-header auth, never cookies, so credentials stay off.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if settings.hsts_enabled:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


app.include_router(auth.router)
app.include_router(suite_auth.router)
app.include_router(users.router)
app.include_router(items.router)
app.include_router(meta.router)
app.include_router(templates.router)
app.include_router(ebay.router)
app.include_router(messages.router)
app.include_router(shipping.router)
app.include_router(settings_router.router)


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}


@app.get("/version", tags=["version"])
async def version() -> dict:
    # Unauthenticated (like /health) so the app can show what's running before/after login.
    return {
        "name": app.title,
        "version": APP_VERSION,
        "commit": settings.git_sha,
        "built_at": settings.built_at,
    }
