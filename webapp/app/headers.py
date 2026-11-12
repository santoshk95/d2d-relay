"""Security headers on every answer of the public site and the admin portal, and a guard for the Range header
(security audit, 2026-11-11).

  X-Content-Type-Options: nosniff         a file is only what its type says
  Referrer-Policy: strict-origin-when-cross-origin
                                          another site (Razorpay's checkout too) sees only the site's address, never a page
  X-Frame-Options: SAMEORIGIN, and CSP frame-ancestors 'self'
                                          no other site can show D2D Relay in a frame (clickjacking)
  CSP object-src 'none'; base-uri 'self'  no plug-ins, no <base> redirecting the app's own links
                                          (a page with a policy of its own, such as a prototype or an invoice, keeps it)
  Strict-Transport-Security               on an https site: browsers use https only, for a year
Scripts are not limited yet (the screens and Razorpay's checkout would need a list of their sources first).

A Range header asking for several ranges is dropped (the whole file is sent instead): Starlette 0.41 merges ranges in
quadratic time (CVE-2025-62727), so one request could hold the site's processor. One range (resuming a download) works
as before. Upgrading FastAPI/Starlette removes the need for this.
"""
from __future__ import annotations

from fastapi import Request

from . import identity

BASE_CSP = "frame-ancestors 'self'; object-src 'none'; base-uri 'self'"
HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "strict-origin-when-cross-origin",
           "X-Frame-Options": "SAMEORIGIN"}
HSTS = "max-age=31536000"


def _headers(scope_headers: list) -> list:
    """The request's headers without a Range header of several ranges."""
    return [(k, v) for k, v in scope_headers if not (k.lower() == b"range" and b"," in v)]


async def middleware(request: Request, call_next):
    request.scope["headers"] = _headers(request.scope.get("headers") or [])
    response = await call_next(request)
    for k, v in HEADERS.items():
        response.headers.setdefault(k, v)
    if "content-security-policy" not in response.headers:
        response.headers["Content-Security-Policy"] = BASE_CSP
    if identity.SECURE_COOKIE:
        response.headers.setdefault("Strict-Transport-Security", HSTS)
    return response
