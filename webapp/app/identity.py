"""Sign-in (platform plan, phase 1): SSO over OpenID Connect, a local password for the bootstrap admin only, and
server-side sessions.

SSO: authorization code flow with PKCE (S256), state and nonce; the ID token's signature is checked against the
provider's published keys (JWKS), plus issuer, audience, expiry and nonce. Works with Microsoft Entra ID, Okta and
Google Workspace (any OIDC provider with discovery). Providers are configured by an Admin (stored in the index
database; client secrets in the encrypted secrets store). People are matched by email: an Admin adds them first,
or a provider may create new people automatically (no team, so they see nothing until an Admin adds them).

Sessions: a random id in an HttpOnly, SameSite=Lax cookie; the row in `sessions` holds who and until when.

P17 (tenants): providers, sessions and sign-in flows live in each tenant's own schema. The session cookie carries the
home tenant (`<tenant>~<id>`; no prefix = the platform's), so does the OIDC `state` (redirect URIs do not change).
Each tenant's first admin may also sign in with a local password, set once through a setup link (72 hours).
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import urlencode

import httpx
import jwt

from . import db, portal, secrets_store

COOKIE = portal.COOKIE                 # D2D Relay: d2d_session on the public site, d2d_admin on the admin portal
SEP = "~"                              # <tenant>~<session id> / <tenant>~<state>; ids from token_urlsafe never contain it
SETUP_HOURS = 72
SESSION_HOURS = float(os.environ.get("D2D_SESSION_HOURS", "12"))
PUBLIC_URL = os.environ.get("D2D_PUBLIC_URL", "").rstrip("/")
SECURE_COOKIE = PUBLIC_URL.startswith("https://")
FLOW_S = 900
_discovery: dict[str, tuple[float, dict]] = {}
_jwks: dict[str, jwt.PyJWKClient] = {}
_failures: dict[str, list[float]] = {}


class SignInError(Exception):
    """Shown to the person on the sign-in page."""


# ---------------------------------------------------------------- local password (bootstrap admin only)

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str | None) -> bool:
    try:
        kind, salt, digest = (stored or "").split("$")
        if kind != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(got, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def set_local_password(uid: str, password: str) -> None:
    if len(password) < 12:
        raise SignInError("Use at least 12 characters.")
    db.run("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), uid))


def bootstrap_password() -> None:
    """D2D_ADMIN_PASSWORD sets the bootstrap admin's local password (only the bootstrap admin has one)."""
    pw = os.environ.get("D2D_ADMIN_PASSWORD")
    if pw:
        u = db.one("SELECT password_hash FROM users WHERE id = ?", (db.ADMIN_ID,))
        if not (u and verify_password(pw, u["password_hash"])):
            set_local_password(db.ADMIN_ID, pw)


def local_enabled() -> bool:
    """Whether this tenant's sign-in page offers the local form (the bootstrap admin, or a tenant's first admin)."""
    return bool(db.one("SELECT 1 FROM users WHERE (id = ? OR local_login = 1) AND password_hash IS NOT NULL AND active = 1 "
                       "AND home_tenant IS NULL", (db.ADMIN_ID,)))


def _throttle(key: str) -> None:
    now = time.time()
    recent = [t for t in _failures.get(key, []) if now - t < 900]
    _failures[key] = recent
    if len(recent) >= 5:
        raise SignInError("Too many attempts. Wait 15 minutes and try again.")


def local_sign_in(email: str, password: str, ip: str) -> dict:
    email = email.strip().lower()
    for key in (f"e:{email}", f"i:{ip}"):
        _throttle(key)
    u = db.one("SELECT * FROM users WHERE lower(email) = ? AND (id = ? OR local_login = 1) AND active = 1 AND home_tenant IS NULL",
               (email, db.ADMIN_ID))
    if not u or not verify_password(password, u["password_hash"]):
        for key in (f"e:{email}", f"i:{ip}"):
            _failures.setdefault(key, []).append(time.time())
        db.audit("auth.denied", email, {"provider": "local", "ip": ip}, None)
        raise SignInError("That email and password do not match the local admin account.")
    return u


# ---------------------------------------------------------------- setup links (P17: a new tenant's first admin)

def create_setup(uid: str) -> str:
    """A one-time link token for a person of the current tenant to set their local password (72 hours). Only a hash
    is kept; the token is shown once to whoever created the tenant."""
    token = secrets.token_urlsafe(24)
    now = time.time()
    db.run("UPDATE users SET local_login = 1 WHERE id = ?", (uid,))
    db.run("INSERT INTO relay.tn_setup (token, tenant_id, user_id, created, expires) VALUES (?, ?, ?, ?, ?)",
           (_hash(token), db.tenant(), uid, now, now + SETUP_HOURS * 3600))
    return token


def setup_tenant(token: str) -> str | None:
    """The tenant a setup token belongs to (to open the right schema before using it), or None."""
    row = db.one("SELECT tenant_id FROM relay.tn_setup WHERE token = ? AND used IS NULL AND expires > ?", (_hash(token or ""), time.time()))
    return row["tenant_id"] if row else None


def use_setup(token: str, password: str) -> dict:
    """Set the local password with a setup token (in the token's tenant). Returns the person; the link then dies."""
    row = db.one("SELECT * FROM relay.tn_setup WHERE token = ? AND used IS NULL AND expires > ?", (_hash(token or ""), time.time()))
    if not row or row["tenant_id"] != db.tenant():
        raise SignInError("This set-up link has expired or was already used. Ask for a new one.")
    u = db.one("SELECT * FROM users WHERE id = ? AND active = 1", (row["user_id"],))
    if not u:
        raise SignInError("This account is no longer active.")
    set_local_password(u["id"], password)
    db.run("UPDATE users SET local_login = 1 WHERE id = ?", (u["id"],))
    db.run("UPDATE relay.tn_setup SET used = ? WHERE token = ?", (time.time(), row["token"]))
    db.audit("auth.setup", u["id"], {"tenant": db.tenant()}, u["id"])
    return u


# ---------------------------------------------------------------- sessions

def split_cookie(value: str | None) -> tuple[str, str | None]:
    """(home tenant, session id) from the cookie; a cookie without a tenant is the platform's (as before P17)."""
    if not value:
        return db.PLATFORM, None
    if SEP in value:
        t, sid = value.split(SEP, 1)
        return t, sid
    return db.PLATFORM, value


def cookie_value(sid: str) -> str:
    """The cookie for a session made in the current tenant."""
    t = db.tenant()
    return sid if t == db.PLATFORM else f"{t}{SEP}{sid}"


def session_key(sid: str | None) -> str:
    """What the acting tenant of this browser session is kept under (relay.tn_acting)."""
    return "s:" + _hash(sid) if sid else ""

def create_session(uid: str, provider: str, ip: str = "", agent: str = "") -> str:
    sid = secrets.token_urlsafe(32)
    now = time.time()
    db.run("INSERT INTO sessions (id, user_id, provider, created, expires, last_seen, ip, agent) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
           (_hash(sid), uid, provider, now, now + SESSION_HOURS * 3600, now, ip, agent[:200]))
    db.run("UPDATE users SET last_login = ?, auth_provider = ? WHERE id = ?", (now, provider, uid))
    db.audit("auth.login", uid, {"provider": provider, "ip": ip}, uid)
    return sid


def _hash(sid: str) -> str:
    """Only a hash of the session id is stored, so a copy of the database cannot be used to sign in."""
    return hashlib.sha256(sid.encode()).hexdigest()


def session_user(sid: str | None) -> dict | None:
    if not sid:
        return None
    row = db.one("SELECT * FROM sessions WHERE id = ? AND expires > ?", (_hash(sid), time.time()))
    if not row:
        return None
    if (row["provider"] == portal.SESSION_KIND) != portal.ADMIN:   # D2D Relay: each site accepts only its own sessions
        return None
    u = db.user(row["user_id"])
    if not u:
        return None
    if time.time() - row["last_seen"] > 60:
        db.run("UPDATE sessions SET last_seen = ? WHERE id = ?", (time.time(), row["id"]))
    return u


def end_session(sid: str | None) -> None:
    if sid:
        db.run("DELETE FROM sessions WHERE id = ?", (_hash(sid),))
        db.run("DELETE FROM relay.tn_acting WHERE skey = ?", (session_key(sid),))


def end_user_sessions(uid: str) -> int:
    return db.run("DELETE FROM sessions WHERE user_id = ?", (uid,))


# ---------------------------------------------------------------- SSO providers (OIDC)

KINDS = {"entra": "Microsoft", "google": "Google", "okta": "Okta", "oidc": "SSO"}


def providers(public: bool = False) -> list[dict]:
    """Configured providers. public=True: only what the sign-in page needs (id, label, kind)."""
    items = json.loads(db.meta("sso_providers") or "[]")
    if public:
        return [{"id": p["id"], "label": p.get("label") or KINDS.get(p.get("kind"), "SSO"), "kind": p.get("kind", "oidc")}
                for p in items if p.get("enabled", True)]
    for p in items:
        p["has_secret"] = secrets_store.get("org", f"sso:{p['id']}:client_secret") is not None
    return items


def save_providers(items: list[dict], secrets_by_id: dict[str, str], who: str | None) -> list[dict]:
    clean = []
    for p in items:
        pid = str(p.get("id", "")).strip().lower()
        if not pid.isidentifier() or not p.get("issuer") or not p.get("client_id"):
            raise SignInError("Each provider needs an id (letters, digits, _), an issuer URL and a client id.")
        if not str(p["issuer"]).startswith("https://") and os.environ.get("D2D_ALLOW_HTTP_ISSUER") != "1":   # tests only
            raise SignInError("The issuer must be an https:// URL.")
        clean.append({"id": pid, "kind": p.get("kind") if p.get("kind") in KINDS else "oidc",
                      "label": str(p.get("label") or KINDS.get(p.get("kind"), "SSO"))[:60],
                      "issuer": str(p["issuer"]).rstrip("/"), "client_id": str(p["client_id"]).strip(),
                      "scopes": str(p.get("scopes") or "openid email profile"),
                      "allowed_domains": [d.strip().lower().lstrip("@") for d in p.get("allowed_domains") or [] if d.strip()],
                      "auto_provision": bool(p.get("auto_provision")), "enabled": bool(p.get("enabled", True))})
    if len({p["id"] for p in clean}) != len(clean):
        raise SignInError("Provider ids must be different.")
    for pid, secret in secrets_by_id.items():
        if secret:
            secrets_store.put("org", f"sso:{pid}:client_secret", secret, who)
    db.set_meta("sso_providers", json.dumps(clean))
    _discovery.clear()
    db.audit("sso.config", None, {"providers": [p["id"] for p in clean]}, who)
    return providers()


def _provider(pid: str) -> dict:
    p = next((x for x in json.loads(db.meta("sso_providers") or "[]") if x["id"] == pid and x.get("enabled", True)), None)
    if not p:
        raise SignInError("This sign-in option is not set up.")
    return p


def _discover(issuer: str) -> dict:
    hit = _discovery.get(issuer)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    r = httpx.get(issuer + "/.well-known/openid-configuration", timeout=10)
    r.raise_for_status()
    conf = r.json()
    _discovery[issuer] = (time.time(), conf)
    return conf


def redirect_uri(pid: str, base_url: str) -> str:
    return f"{PUBLIC_URL or base_url.rstrip('/')}/auth/oidc/{pid}/callback"


def start(pid: str, base_url: str, return_to: str = "") -> str:
    """The URL to send the browser to; remembers state, nonce and the PKCE verifier for the callback."""
    p = _provider(pid)
    conf = _discover(p["issuer"])
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    if db.tenant() != db.PLATFORM:                    # the callback finds the flow in this tenant (auth middleware)
        state = f"{db.tenant()}{SEP}{state}"
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    db.run("INSERT INTO auth_flows (state, provider, verifier, nonce, return_to, created) VALUES (?, ?, ?, ?, ?, ?)",
           (state, pid, verifier, nonce, return_to if return_to.startswith("#/") else "", time.time()))
    q = {"response_type": "code", "client_id": p["client_id"], "redirect_uri": redirect_uri(pid, base_url),
         "scope": p["scopes"], "state": state, "nonce": nonce, "code_challenge": challenge,
         "code_challenge_method": "S256"}
    return conf["authorization_endpoint"] + ("&" if "?" in conf["authorization_endpoint"] else "?") + urlencode(q)


def _email(claims: dict) -> str:
    email = claims.get("email") or claims.get("preferred_username") or claims.get("upn") or ""
    if claims.get("email_verified") is False:
        raise SignInError("Your identity provider says this email address is not verified.")
    if "@" not in email:
        raise SignInError("Your identity provider did not send an email address.")
    return email.strip().lower()


def callback(pid: str, code: str, state: str, base_url: str) -> tuple[dict, str]:
    """Finish SSO: exchange the code, verify the ID token, find or create the person. Returns (user, return_to)."""
    flow = db.one("SELECT * FROM auth_flows WHERE state = ? AND provider = ?", (state, pid))
    db.run("DELETE FROM auth_flows WHERE state = ?", (state,))          # one use only
    if not flow or time.time() - flow["created"] > FLOW_S:
        raise SignInError("The sign-in took too long or was already used. Please try again.")
    p = _provider(pid)
    conf = _discover(p["issuer"])
    secret = secrets_store.get("org", f"sso:{pid}:client_secret")
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(pid, base_url),
            "client_id": p["client_id"], "code_verifier": flow["verifier"]}
    if secret:
        form["client_secret"] = secret
    r = httpx.post(conf["token_endpoint"], data=form, timeout=15, headers={"Accept": "application/json"})
    if r.status_code != 200:
        raise SignInError("Your identity provider did not accept the sign-in.")
    token = r.json().get("id_token")
    if not token:
        raise SignInError("Your identity provider did not send an ID token.")
    claims = _verify(token, p, conf, flow["nonce"])
    email = _email(claims)
    domain = email.split("@", 1)[1]
    if p["allowed_domains"] and domain not in p["allowed_domains"]:
        db.audit("auth.denied", email, {"provider": pid, "reason": "domain"}, None)
        raise SignInError(f"Accounts from {domain} cannot sign in here.")
    u = db.one("SELECT * FROM users WHERE lower(email) = ? AND home_tenant IS NULL", (email,))   # own people, not guests
    if u and not u["active"]:
        db.audit("auth.denied", email, {"provider": pid, "reason": "deactivated"}, None)
        raise SignInError("Your D2D account is deactivated. Ask your administrator.")
    if not u:
        if not p["auto_provision"]:
            db.audit("auth.denied", email, {"provider": pid, "reason": "not added"}, None)
            raise SignInError("You have not been added to D2D yet. Ask your administrator to add you.")
        from . import orgs                              # late import (orgs -> identity)
        if orgs.is_blocked(db.tenant(), email):         # item 32: an owner removed this address
            db.audit("auth.denied", email, {"provider": pid, "reason": "blocked"}, None)
            raise SignInError("An owner of your organisation removed this address. Ask one of its owners to add you back.")
        home = db.one("SELECT home_tenant FROM relay.tn_accounts WHERE email = ?", (email,))
        if home and home["home_tenant"] != db.tenant():
            db.audit("auth.denied", email, {"provider": pid, "reason": "other workspace"}, None)
            raise SignInError("This email address belongs to another workspace. Sign in there, or ask an administrator.")
        uid = "u-" + secrets.token_hex(6)
        db.run("INSERT INTO users (id, email, name, org_role, created) VALUES (?, ?, ?, 'member', ?)",
               (uid, email, (claims.get("name") or email.split("@")[0])[:120], time.time()))
        db.run("INSERT OR IGNORE INTO relay.tn_accounts (user_id, email, home_tenant, created) VALUES (?, ?, ?, ?)",
               (uid, email, db.tenant(), time.time()))
        db.audit("user.provisioned", uid, {"email": email, "provider": pid}, uid)
        u = db.one("SELECT * FROM users WHERE id = ?", (uid,))
    return u, flow["return_to"] or ""


def _verify(token: str, p: dict, conf: dict, nonce: str) -> dict:
    jwks_uri = conf["jwks_uri"]
    if jwks_uri not in _jwks:
        _jwks[jwks_uri] = jwt.PyJWKClient(jwks_uri, cache_keys=True, lifespan=3600)
    try:
        key = _jwks[jwks_uri].get_signing_key_from_jwt(token)
        unverified = jwt.decode(token, options={"verify_signature": False})
        issuer = conf["issuer"].replace("{tenantid}", str(unverified.get("tid", "")))   # Entra multi-tenant
        claims = jwt.decode(token, key.key, algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "PS256"],
                            audience=p["client_id"], issuer=issuer, leeway=60,
                            options={"require": ["exp", "iat", "iss", "aud", "sub"]})
    except jwt.PyJWTError as e:
        raise SignInError(f"The ID token from your identity provider is not valid ({e.__class__.__name__}).") from e
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise SignInError("The sign-in response did not match this request. Please try again.")
    return claims
