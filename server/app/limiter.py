from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.config import settings


def client_key(request: Request) -> str:
    """Rate-limit key = the real client IP.

    Behind a trusted proxy every request reaches the app from the proxy, so keying on the
    socket peer would lump all users together. When ``trust_proxy`` is enabled we use the
    forwarded client IP instead. Disabled by default so a directly-exposed server can't be
    spoofed via forged headers (Crate is tailnet-only, so the default is what runs).
    """
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=client_key)
