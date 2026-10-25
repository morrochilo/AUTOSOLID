"""Minimal local review UI served by the FastAPI application.

The UI is deliberately dependency-free: static HTML, CSS and JavaScript that
consume the existing ``/api/v1`` endpoints. No external assets, build step or
secrets are involved.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

router = APIRouter(include_in_schema=False)

_CSP = (
    "default-src 'self'; "
    "base-uri 'none'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'"
)

_SECURITY_HEADERS = {
    "Content-Security-Policy": _CSP,
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=(), payment=()",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}

_DOCUMENT_HEADERS = {**_SECURITY_HEADERS, "Cache-Control": "no-store"}
_ASSET_HEADERS = {**_SECURITY_HEADERS, "Cache-Control": "no-cache"}


@lru_cache(maxsize=3)
def _read_asset(name: str) -> str:
    static = files("autosolid.api").joinpath("static")
    return static.joinpath(name).read_text(encoding="utf-8")


@router.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(_read_asset("index.html"), headers=_DOCUMENT_HEADERS)


@router.get("/ui/app.css", response_class=Response)
def styles() -> Response:
    return Response(
        _read_asset("app.css"),
        media_type="text/css",
        headers=_ASSET_HEADERS,
    )


@router.get("/ui/app.js", response_class=Response)
def script() -> Response:
    return Response(
        _read_asset("app.js"),
        media_type="text/javascript",
        headers=_ASSET_HEADERS,
    )
