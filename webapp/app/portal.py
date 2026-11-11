"""D2D Relay: which site this process serves, set per container by D2D_PORTAL (RELAY_PORTAL in .env).

  public  https://d2d-relay.pasdacs.com (container d2d-relay-web): organisations sign in with a business email and
          build dashboards. Nobody has platform powers here: every /api/admin path answers 404.
  admin   https://admin-d2d.pasdacs.com (container d2d-relay-admin): PASDACS only. Two locks, both required:
          1. Cloudflare Access in front of the hostname. Every request that comes through Cloudflare (it carries
             cf-connecting-ip) must bring Access's signed token (Cf-Access-Jwt-Assertion) for this application
             (D2D_ADMIN_ACCESS_TEAM, D2D_ADMIN_ACCESS_AUD) and for an address at an admin domain. Until those two
             settings are filled in, nothing gets through the tunnel: the portal works on this PC only.
          2. The app's own email code, for addresses at D2D_ADMIN_DOMAINS (pasdacs.com) only. Everyone signed in
             here is a platform admin. The session has its own cookie and kind ("otp-admin"), so a session from the
             public site is never accepted here, nor one from here there.
          The admin portal answers only the APIs in API (organisations, requests, notifications, who am I); it runs
          no AI engine, no job queue and no schedules.
"""
from __future__ import annotations

import os

NAME = (os.environ.get("D2D_PORTAL") or "public").strip().lower()
ADMIN = NAME == "admin"
ADMIN_DOMAINS = [d.strip().lower().lstrip("@") for d in (os.environ.get("D2D_ADMIN_DOMAINS") or "pasdacs.com").split(",") if d.strip()]
SESSION_KIND = "otp-admin"                  # identity.create_session's provider for admin-portal sessions
COOKIE = "d2d_admin" if ADMIN else "d2d_session"
_team = (os.environ.get("D2D_ADMIN_ACCESS_TEAM") or "").strip().lower().removeprefix("https://").rstrip("/")
ACCESS_TEAM = _team if "." in _team or not _team else f"{_team}.cloudflareaccess.com"
ACCESS_AUD = (os.environ.get("D2D_ADMIN_ACCESS_AUD") or "").strip()
# What the admin portal answers under /api (everything else there is 404)
API = ("/api/me", "/api/registry", "/api/brand", "/api/notifications", "/api/admin/orgs", "/api/admin/requests")
_jwks = None


def admin_email(email: str | None) -> bool:
    return (email or "").strip().lower().rsplit("@", 1)[-1] in ADMIN_DOMAINS and "@" in (email or "")


def is_admin(u: dict | None) -> bool:
    """A PASDACS person working in the platform's own workspace (never a guest row, never switched off)."""
    from . import db
    t = (u or {}).get("_tenancy") or {}
    return bool(u) and bool(u.get("active", 1)) and not u.get("home_tenant") and admin_email(u.get("email")) \
        and t.get("home") == db.PLATFORM and t.get("tenant") == db.PLATFORM


def api_allowed(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") or path.startswith(p + "?") for p in API)


def access_refusal(headers, cookies) -> str | None:
    """None when this request may go on to the admin portal's own sign-in; otherwise why not (HTTP 403).
    From this PC (no cf-connecting-ip: the port is published on 127.0.0.1 only) there is nothing to check."""
    global _jwks
    if not headers.get("cf-connecting-ip"):
        return None
    if not (ACCESS_TEAM and ACCESS_AUD):
        return ("The admin portal is not open through the internet yet: Cloudflare Access is not set up for it "
                "(D2D_ADMIN_ACCESS_TEAM, D2D_ADMIN_ACCESS_AUD). Use it on the D2D Relay PC for now.")
    token = headers.get("cf-access-jwt-assertion") or cookies.get("CF_Authorization")
    if not token:
        return "Sign in through Cloudflare Access first."
    import jwt
    try:
        if _jwks is None:
            _jwks = jwt.PyJWKClient(f"https://{ACCESS_TEAM}/cdn-cgi/access/certs", cache_keys=True, lifespan=3600)
        key = _jwks.get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=ACCESS_AUD, issuer=f"https://{ACCESS_TEAM}",
                            leeway=60, options={"require": ["exp", "iat", "iss", "aud"]})
    except Exception:  # noqa: BLE001 - an expired, foreign or forged token, or the keys could not be read
        return "Cloudflare Access did not vouch for this request. Sign in through Cloudflare Access again."
    if not admin_email(claims.get("email")):
        return "The admin portal is for PASDACS addresses only."
    return None
