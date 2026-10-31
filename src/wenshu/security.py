"""Local-only request hardening: token check, host check, origin check."""

from __future__ import annotations

import hmac
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def token_matches(supplied: str | None, expected: str) -> bool:
    if not supplied:
        return False
    return hmac.compare_digest(supplied, expected)


def host_allowed(request: Request, allowed_hosts: set[str]) -> bool:
    host = (request.headers.get("host") or "").strip()
    if not host:
        return False
    hostname = host
    if host.startswith("["):
        hostname = host.split("]")[0] + "]"
    else:
        hostname = host.split(":")[0]
    return hostname.lower() in {h.lower() for h in allowed_hosts}


def origin_allowed(request: Request, allowed_hosts: set[str]) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return True
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"}:
        return False
    return (parsed.hostname or "").lower() in {h.lower() for h in allowed_hosts}


class TokenMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, token: str, allowed_hosts: set[str]):
        super().__init__(app)
        self.token = token
        self.allowed_hosts = allowed_hosts

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Host check applies to pages too: DNS rebinding could otherwise read a
        # server-rendered page (with its token) through an attacker-controlled name.
        if not host_allowed(request, self.allowed_hosts):
            if path.startswith("/api"):
                body = {"error": {"code": "bad_host", "message": "只允许本机访问。"}}
                return JSONResponse(body, status_code=403)
            return JSONResponse(
                {"error": {"code": "bad_host", "message": "只允许通过本机地址访问。"}},
                status_code=403,
            )
        if path.startswith("/api") and path != "/api/health":
            supplied = request.headers.get("x-wenshu-token")
            auth = request.headers.get("authorization", "")
            if not supplied and auth.lower().startswith("bearer "):
                supplied = auth[7:].strip()
            if not token_matches(supplied, self.token):
                return JSONResponse(
                    {"error": {"code": "unauthorized", "message": "缺少或错误的本地访问令牌。"}},
                    status_code=401,
                )
            if request.method in UNSAFE_METHODS and not origin_allowed(request, self.allowed_hosts):
                return JSONResponse(
                    {"error": {"code": "bad_origin", "message": "拒绝跨站请求。"}},
                    status_code=403,
                )
        return await call_next(request)
