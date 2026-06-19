"""Security primitives: hardened headers, body-size guard, rate limiting and
admin authentication.

These address several OWASP Top 10 categories:
* A01 Broken Access Control     -> constant-time admin token check.
* A04 Insecure Design / abuse   -> per-IP rate limiting + body size cap.
* A05 Security Misconfiguration -> strict security headers + CSP.
"""
from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict
from typing import Dict, List

from fastapi import Header, HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from .config import settings


def client_ip(request: Request) -> str:
    """Best-effort client IP. Trusts X-Forwarded-For ONLY when configured."""
    if settings.trust_proxy:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach a strict set of security headers to every response."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response: Response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=()",
        )
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        # CSP: the frontend loads the PayPal JS SDK (buttons + Apple Pay /
        # Google Pay) and opens Jitsi/PayPal in new tabs, so those origins are
        # allowed for scripts/frames/connections.
        headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "img-src 'self' data: blob: https:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com "
            "https://applepay.cdn-apple.com; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "script-src 'self' 'unsafe-inline' https://www.paypal.com "
            "https://www.paypalobjects.com https://pay.google.com "
            "https://applepay.cdn-apple.com; "
            "connect-src 'self' https://www.paypal.com https://www.sandbox.paypal.com "
            "https://api-m.paypal.com https://api-m.sandbox.paypal.com "
            "https://pay.google.com; "
            "frame-src https://www.paypal.com https://www.sandbox.paypal.com "
            "https://pay.google.com; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'",
        )
        if not settings.debug:
            headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose body exceeds ``max_request_bytes`` (anti-DoS)."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                if int(cl) > settings.max_request_bytes:
                    return Response("Payload too large", status_code=413)
            except ValueError:
                return Response("Invalid Content-Length", status_code=400)
        return await call_next(request)


class RateLimiter:
    """Thread-safe fixed-window in-memory rate limiter.

    Suitable for a single-process deployment. For multi-worker / multi-host
    setups, back this with Redis instead.
    """

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max = max_requests
        self.window = window_seconds
        self._hits: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def hit(self, key: str) -> None:
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            bucket = self._hits[key]
            bucket[:] = [t for t in bucket if t > cutoff]
            if len(bucket) >= self.max:
                retry = int(self.window - (now - bucket[0])) + 1
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Demasiadas solicitudes, intenta más despacio.",
                    headers={"Retry-After": str(max(retry, 1))},
                )
            bucket.append(now)


_write_limiter = RateLimiter(
    settings.write_ratelimit_max, settings.write_ratelimit_window
)
_read_limiter = RateLimiter(
    settings.read_ratelimit_max, settings.read_ratelimit_window
)


def write_rate_limit(request: Request) -> None:
    """FastAPI dependency: throttle write endpoints per client IP."""
    _write_limiter.hit(f"w:{client_ip(request)}:{request.url.path}")


def read_rate_limit(request: Request) -> None:
    """FastAPI dependency: throttle read endpoints per client IP."""
    _read_limiter.hit(f"r:{client_ip(request)}:{request.url.path}")


def require_admin(x_admin_token: str = Header(default="")) -> None:
    """FastAPI dependency: constant-time check of the admin bearer token."""
    expected = settings.resolved_admin_token
    if not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autorizado.",
            headers={"WWW-Authenticate": "Bearer"},
        )
