from __future__ import annotations

import secrets
from collections.abc import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

PUBLIC_API_PATHS = frozenset({
    "/api/v1/health",
    "/api/v1/health/ready",
    "/api/v1/auth/status",
})


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, separator, credentials = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return None
    token = credentials.strip()
    return token or None


def token_matches(authorization: str | None, expected_token: str | None) -> bool:
    if not expected_token:
        return True
    supplied = bearer_token(authorization)
    return bool(supplied) and secrets.compare_digest(supplied, expected_token)


class AccessTokenMiddleware(BaseHTTPMiddleware):
    """Protect business APIs with a deployment-scoped bearer token."""

    def __init__(self, app, *, access_token: str | None) -> None:
        super().__init__(app)
        self.access_token = access_token

    async def dispatch(self, request: Request, call_next: Callable):  # type: ignore[override]
        if (
            not self.access_token
            or request.method == "OPTIONS"
            or not request.url.path.startswith("/api/v1/")
            or request.url.path in PUBLIC_API_PATHS
        ):
            return await call_next(request)

        authorization = request.headers.get("Authorization")
        if token_matches(authorization, self.access_token):
            return await call_next(request)

        code = "ACCESS_TOKEN_INVALID" if bearer_token(authorization) else "ACCESS_TOKEN_REQUIRED"
        message = "访问令牌无效" if code == "ACCESS_TOKEN_INVALID" else "此 MeetingMind 实例需要访问令牌"
        return JSONResponse(
            status_code=401,
            content={"detail": {"code": code, "message": message}},
            headers={"WWW-Authenticate": "Bearer"},
        )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Apply non-cache and browser hardening headers to every API response."""

    async def dispatch(self, request: Request, call_next: Callable):  # type: ignore[override]
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("Referrer-Policy", "no-referrer")
            response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response
