"""LiteLLM custom auth for Relay: accept only run keys signed by the Relay web app.

A key is  d2d.<base64url(json {u: user, t: [team ids], n: tenant, exp: unix time})>.<base64url(HMAC-SHA256(body))>,
signed with /data/llm/signing.key (written by the web app). The requested model must be a route in
/data/llm/routes.json of the key's own tenant (P17: "" = the platform; team ids repeat across tenants) that allows one
of the key's teams (or every team). Anything else is refused before LiteLLM calls a provider.
"""
import base64
import hashlib
import hmac
import json
import time

from fastapi import Request
from litellm.proxy._types import ProxyException, UserAPIKeyAuth

DIR = "/data/llm"


def _b64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _deny(message: str) -> ProxyException:
    """LiteLLM's own auth error: a 401 to the caller, nothing reaches a provider."""
    return ProxyException(message=f"D2D gateway: {message}", type="auth_error", param="api_key", code=401)


def _read(name: str) -> str:
    with open(f"{DIR}/{name}", encoding="utf-8") as f:
        return f.read()


async def user_api_key_auth(request: Request, api_key: str) -> UserAPIKeyAuth:
    token = (api_key or "").removeprefix("Bearer ").strip()
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != "d2d":
        raise _deny("not a D2D key")
    expected = base64.urlsafe_b64encode(hmac.new(_read("signing.key").strip().encode(), parts[1].encode(),
                                                 hashlib.sha256).digest()).rstrip(b"=").decode()
    if not hmac.compare_digest(expected, parts[2]):
        raise _deny("bad signature")
    claims = json.loads(_b64(parts[1]))
    if claims.get("exp", 0) < time.time():
        raise _deny("key expired")
    model = None
    if request.method == "POST":
        try:
            model = json.loads(await request.body() or b"{}").get("model")
        except ValueError:
            model = None
    tenant = claims.get("n") or ""
    routes = {m: r for m, r in json.loads(_read("routes.json")).items() if (r.get("tenant") or "") == tenant}
    if model is not None:
        route = routes.get(model)
        if route is None:
            raise _deny(f"no route named {model}")
        if route.get("teams") and not set(route["teams"]) & set(claims.get("t") or []):
            raise _deny(f"{model} is not available to this person's teams")
    allowed = [m for m, r in routes.items() if not r.get("teams") or set(r["teams"]) & set(claims.get("t") or [])]
    return UserAPIKeyAuth(api_key=None, user_id=claims["u"], models=allowed)
