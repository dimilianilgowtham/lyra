"""Authenticate the loopback service without putting provider keys in the UI."""
import secrets

from fastapi import Request, WebSocket
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from config import settings

COOKIE_NAME = "lyra_session"


def valid_token(value: str | None) -> bool:
    return bool(value) and secrets.compare_digest(str(value), settings.BACKEND_AUTH_TOKEN)


def authenticated(headers, cookies) -> bool:
    bearer = headers.get("authorization", "")
    if bearer.startswith("Bearer ") and valid_token(bearer[7:]):
        return True
    return valid_token(cookies.get(COOKIE_NAME))


def allowed_origin(origin: str | None, *, bearer: bool = False) -> bool:
    return origin is None or origin in settings.ALLOWED_ORIGINS or (origin == "null" and bearer)


class LocalAccessMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        bearer = request.headers.get("authorization", "").startswith("Bearer ")
        origin = request.headers.get("origin")
        if not allowed_origin(origin, bearer=bearer):
            return JSONResponse({"error": "This origin cannot access the local assistant."}, status_code=403)
        if request.method == "OPTIONS":
            return await call_next(request)
        if request.url.path == "/api/session":
            if origin not in settings.ALLOWED_ORIGINS and not authenticated(request.headers, request.cookies):
                return JSONResponse({"error": "A trusted local browser origin is required."}, status_code=403)
        elif not authenticated(request.headers, request.cookies):
            return JSONResponse({"error": "Local assistant authentication is required."}, status_code=401)
        return await call_next(request)


def websocket_authenticated(socket: WebSocket) -> bool:
    query_token = socket.query_params.get("token")
    has_token = valid_token(query_token) or authenticated(socket.headers, socket.cookies)
    return has_token and allowed_origin(socket.headers.get("origin"), bearer=valid_token(query_token))
