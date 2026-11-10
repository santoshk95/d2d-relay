"""Bring your own AI (platform plan, phase 2): which model provider each person's runs use, and the LiteLLM gateway.

A person picks one of the kinds the Admin's AI policy allows:
  claude_account  Claude Docker, as today: the installation's Claude login, or the person's own Claude subscription
                  token (from `claude setup-token`) so the cost goes to their subscription
  anthropic_api   their Anthropic API key
  litellm         a route of the LiteLLM gateway: Amazon Bedrock, Azure AI Foundry or Google Vertex AI. Admins set
                  the routes (credentials per provider, which teams may use each); Claude Code reaches them through
                  LiteLLM's Anthropic-compatible API with a short-lived key D2D signs for the run
  enterprise      an endpoint of their own organisation that speaks the Anthropic API (base URL + token)
  codex           OpenAI Codex CLI with their OpenAI API key (phase 8: another runner, its own agent image)
  gemini          Gemini CLI with their Gemini API key (phase 8)
  antigravity     Antigravity CLI with their Gemini API key, or without one the installation's Google login (the
                  antigravity-api gateway's sign-in, shared read-only with the runner image)
Every run gets only the environment its owner's choice needs (agent runner: PROVIDER_ENV). Secrets live in the
secrets store; nothing here is ever returned by the API. A backup provider (the person's, else the policy's) takes
over once when the main one fails with an authentication, quota, rate-limit or outage error.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path

import yaml

from . import db, secrets_store

GATEWAY_URL = os.environ.get("D2D_LITELLM_URL", "http://litellm:4000")
GATEWAY_DIR = Path(os.environ.get("D2D_LITELLM_DIR", "/data/llm"))
KINDS = {"claude_account": "Claude Docker (Claude account)", "anthropic_api": "Anthropic API key",
         "litellm": "LiteLLM gateway (Bedrock, Azure AI Foundry, Vertex)", "enterprise": "Enterprise endpoint",
         "codex": "OpenAI Codex CLI (OpenAI API key)", "gemini": "Gemini CLI (Gemini API key)",
         "antigravity": "Antigravity CLI (Google login or Gemini API key)"}
# phase 8: kinds that run on another CLI -> (runner name, the secret it needs, the variable the CLI reads, label)
CLI_KINDS = {"codex": ("codex", "openai_api_key", "CODEX_API_KEY", "OpenAI Codex CLI"),
             "gemini": ("gemini", "gemini_api_key", "GEMINI_API_KEY", "Gemini CLI"),
             "antigravity": ("antigravity", "gemini_api_key", "GEMINI_API_KEY", "Antigravity CLI")}
# CLI kinds that may run on the installation's own login when the person stores no key
SHARED_LOGIN_KINDS = {"antigravity"}
SECRET_FIELDS = ("claude_oauth_token", "anthropic_api_key", "enterprise_token", "openai_api_key", "gemini_api_key")
CLI_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}$")
ROUTE_PROVIDERS = {"bedrock": "Amazon Bedrock", "azure_foundry": "Azure AI Foundry", "vertex": "Google Vertex AI",
                   "anthropic": "Anthropic API (shared key)"}
ROUTE_SECRETS = {"bedrock": ["aws_access_key_id", "aws_secret_access_key"], "azure_foundry": ["api_key"],
                 "vertex": ["service_account_json"], "anthropic": ["api_key"]}
ALIAS = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}$")
FAILOVER = re.compile(r"\b(401|403|429|529)\b|overloaded|rate.?limit|quota|credit balance|authenticat|invalid (x-)?api.?key|"
                      r"unauthori[sz]ed|oauth token|ECONNREFUSED|ENOTFOUND|API Error: 5\d\d|Connection error", re.I)
_GATEWAY_SECRET_NAME = "llm_gateway_signing_key"


class ProviderError(Exception):
    pass


def _policy() -> dict:
    from .platform import ai_policy          # late import: platform imports worker, worker imports providers
    return ai_policy()


def _allowed(kind: str, route: dict | None = None) -> bool:
    allowed = set(_policy()["allowed"])
    if kind == "litellm":
        return bool(route) and (route["provider"] in allowed or (route["provider"] == "anthropic" and "anthropic_api" in allowed))
    return kind in allowed


# ---------------------------------------------------------------- the person's settings

def settings(uid: str) -> dict:
    raw = json.loads(db.meta(f"ai:{uid}") or "{}")
    s = {"kind": raw.get("kind") or "claude_account", "route": raw.get("route"), "base_url": raw.get("base_url") or "",
         "backup": raw.get("backup"), "cli_model": raw.get("cli_model") or ""}
    s["has_secret"] = {n: secrets_store.get(f"user:{uid}", n) is not None for n in SECRET_FIELDS}
    return s


def save(uid: str, body: dict, who: str | None) -> dict:
    kind = body.get("kind") or "claude_account"
    if kind not in KINDS:
        raise ProviderError("Unknown provider.")
    route = routes_by_alias().get(body.get("route") or "") if kind == "litellm" else None
    if kind == "litellm" and not (route and route_allowed_for(uid, route)):
        raise ProviderError("Pick a gateway route that your team may use.")
    if not _allowed(kind, route):
        raise ProviderError("Your administrator does not allow this provider.")
    base_url = (body.get("base_url") or "").strip().rstrip("/")
    if kind == "enterprise" and not base_url.startswith("https://"):
        raise ProviderError("The enterprise endpoint must be an https:// URL.")
    backup = body.get("backup") or None
    if backup and backup not in ("claude_account", "litellm"):
        raise ProviderError("The backup can be Claude Docker or the gateway route of the policy.")
    cli_model = (body.get("cli_model") or "").strip()
    if kind in CLI_KINDS and cli_model and not CLI_MODEL.match(cli_model):
        raise ProviderError("The model name has unexpected characters.")
    for field, name in ((f, f) for f in SECRET_FIELDS):
        value = (body.get(field) or "").strip()
        if value:
            secrets_store.put(f"user:{uid}", name, value, who)
        elif body.get("clear_" + field):
            secrets_store.delete(f"user:{uid}", name, who)
    if kind == "anthropic_api" and not secrets_store.get(f"user:{uid}", "anthropic_api_key"):
        raise ProviderError("Paste your Anthropic API key.")
    if kind == "enterprise" and not secrets_store.get(f"user:{uid}", "enterprise_token"):
        raise ProviderError("Paste the token for your enterprise endpoint.")
    if kind in CLI_KINDS and kind not in SHARED_LOGIN_KINDS and not secrets_store.get(f"user:{uid}", CLI_KINDS[kind][1]):
        raise ProviderError("Paste your " + ("OpenAI" if kind == "codex" else "Gemini") + " API key.")
    db.set_meta(f"ai:{uid}", json.dumps({"kind": kind, "route": route["alias"] if route else None,
                                         "base_url": base_url if kind == "enterprise" else "", "backup": backup,
                                         "cli_model": cli_model if kind in CLI_KINDS else ""}))
    db.audit("ai.settings", uid, {"kind": kind, "route": route["alias"] if route else None, "backup": backup}, who)
    return settings(uid)


# ---------------------------------------------------------------- gateway routes (Admin)

def routes() -> list[dict]:
    return json.loads(db.meta("llm_routes") or "[]")


def routes_by_alias() -> dict[str, dict]:
    return {r["alias"]: r for r in routes()}


def _teams(uid: str) -> set[str]:
    return {r["team_id"] for r in db.q("SELECT team_id FROM memberships WHERE user_id = ?", (uid,))}


def route_allowed_for(uid: str, route: dict) -> bool:
    return not route.get("teams") or bool(set(route["teams"]) & _teams(uid))


def routes_for(uid: str) -> list[dict]:
    return [r for r in routes() if route_allowed_for(uid, r) and _allowed("litellm", r)]


def save_routes(items: list[dict], creds: dict[str, dict[str, str]], who: str | None) -> list[dict]:
    clean = []
    for r in items:
        alias, provider = str(r.get("alias", "")).strip().lower(), r.get("provider")
        if not ALIAS.match(alias) or provider not in ROUTE_PROVIDERS or not str(r.get("target", "")).strip():
            raise ProviderError("Each route needs a model name (lowercase, e.g. bedrock-sonnet), a provider and the "
                                "provider's model id.")
        clean.append({"alias": alias, "provider": provider, "target": str(r["target"]).strip(),
                      "label": str(r.get("label") or alias)[:80], "region": str(r.get("region") or "").strip(),
                      "api_base": str(r.get("api_base") or "").strip(), "project": str(r.get("project") or "").strip(),
                      "teams": [t for t in r.get("teams") or [] if db.one("SELECT 1 FROM teams WHERE id = ?", (t,))],
                      "small": str(r.get("small") or "").strip().lower() or None})
    if len({r["alias"] for r in clean}) != len(clean):
        raise ProviderError("Model names must be different.")
    for provider, values in (creds or {}).items():
        for name, value in values.items():
            if provider in ROUTE_SECRETS and name in ROUTE_SECRETS[provider] and value:
                secrets_store.put("org", f"llm:{provider}:{name}", value, who)
    db.set_meta("llm_routes", json.dumps(clean))
    db.audit("llm.routes", None, {"routes": [{k: r[k] for k in ("alias", "provider", "target", "teams")} for r in clean]}, who)
    write_gateway_config()
    return routes_admin()


def routes_admin() -> list[dict]:
    out = []
    for r in routes():
        out.append({**r, "has_secrets": {n: secrets_store.get("org", f"llm:{r['provider']}:{n}") is not None
                                         for n in ROUTE_SECRETS[r["provider"]]}})
    return out


def _gateway_key() -> bytes:
    """One signing key for the gateway, whichever tenant asks (P17: kept in the platform's secrets)."""
    with db.use(db.PLATFORM):
        key = secrets_store.get("org", _GATEWAY_SECRET_NAME)
        if not key:
            key = secrets.token_urlsafe(48)
            secrets_store.put("org", _GATEWAY_SECRET_NAME, key, "system")
    return key.encode()


def gateway_model(alias: str, tenant: str | None = None) -> str:
    """The gateway's name for a tenant's route: the alias itself for the platform, `<tenant>.<alias>` for the others
    (P17: every tenant names its own routes; the gateway serves them all)."""
    t = tenant or db.tenant()
    return alias if t == db.PLATFORM else f"{t}.{alias}"


def _litellm_params(r: dict) -> dict:
    sec = lambda n: secrets_store.get("org", f"llm:{r['provider']}:{n}")  # noqa: E731
    if r["provider"] == "bedrock":
        p = {"model": r["target"] if r["target"].startswith("bedrock/") else "bedrock/" + r["target"],
             "aws_access_key_id": sec("aws_access_key_id"), "aws_secret_access_key": sec("aws_secret_access_key"),
             "aws_region_name": r["region"] or "us-east-1"}
    elif r["provider"] == "azure_foundry":
        p = {"model": r["target"] if "/" in r["target"] else "azure_ai/" + r["target"], "api_key": sec("api_key"),
             "api_base": r["api_base"]}
    elif r["provider"] == "vertex":
        p = {"model": r["target"] if r["target"].startswith("vertex_ai/") else "vertex_ai/" + r["target"],
             "vertex_project": r["project"], "vertex_location": r["region"] or "us-east5",
             "vertex_credentials": sec("service_account_json")}
    else:
        p = {"model": r["target"] if "/" in r["target"] else "anthropic/" + r["target"], "api_key": sec("api_key")}
        if r["api_base"]:
            p["api_base"] = r["api_base"]
    return {k: v for k, v in p.items() if v}


def write_gateway_config() -> Path:
    """The LiteLLM proxy's config (models + D2D key check), in a volume only the web app and the gateway mount.
    The gateway restarts to load it (orchestrator) — or picks it up on its next start."""
    GATEWAY_DIR.mkdir(parents=True, exist_ok=True)
    models, table = [], {}
    for t in db.each_tenant():                  # P17: every tenant's routes, each with its own credentials
        for r in routes():
            name = gateway_model(r["alias"], t)
            models.append({"model_name": name, "litellm_params": _litellm_params(r)})
            table[name] = {"teams": r["teams"], "tenant": "" if t == db.PLATFORM else t}
    conf = {"model_list": models,
            "litellm_settings": {"drop_params": True, "request_timeout": 600},
            "general_settings": {"custom_auth": "d2d_auth.user_api_key_auth"}}
    files = {"config.yaml": yaml.safe_dump(conf, sort_keys=False),
             "routes.json": json.dumps(table),
             "signing.key": _gateway_key().decode()}
    for name, text in files.items():
        tmp = GATEWAY_DIR / (name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.chmod(tmp, 0o640)
        tmp.replace(GATEWAY_DIR / name)
    with db.use(db.PLATFORM):
        db.set_meta("llm_config_written", str(time.time()))
    return GATEWAY_DIR / "config.yaml"


def gateway_token(uid: str, ttl_s: int) -> str:
    """A short-lived key for one run: who, their teams, until when — signed with the gateway's key (HMAC-SHA256).
    The gateway checks it and that the requested model's route allows one of the teams."""
    t = db.tenant()
    body = base64.urlsafe_b64encode(json.dumps({"u": uid, "t": sorted(_teams(uid)), "n": "" if t == db.PLATFORM else t,
                                                "exp": int(time.time() + ttl_s)}, separators=(",", ":")).encode()).rstrip(b"=")
    sig = base64.urlsafe_b64encode(hmac.new(_gateway_key(), body, hashlib.sha256).digest()).rstrip(b"=")
    return "d2d." + body.decode() + "." + sig.decode()


# ---------------------------------------------------------------- what a run gets

def run_config(uid: str | None, model: str, ttl_s: int, kind: str | None = None) -> dict:
    """{env, model, provider, kind} for a run owned by `uid`. kind overrides the person's choice (the backup)."""
    s = settings(uid) if uid else {"kind": "claude_account", "route": None, "base_url": ""}
    kind = kind or s["kind"]
    if is_cli_model_id(model) and kind not in CLI_KINDS:     # a CLI pick running on Claude (backup, Ask D): Claude's default
        from .worker import DEFAULT_MODEL                   # late import: worker imports providers
        model = DEFAULT_MODEL
    sec = (lambda n: secrets_store.get(f"user:{uid}", n)) if uid else (lambda n: None)
    if kind == "claude_account":
        token = sec("claude_oauth_token")
        return {"kind": kind, "env": {"CLAUDE_CODE_OAUTH_TOKEN": token} if token else {}, "model": model,
                "provider": "Claude (own subscription)" if token else "Claude (this installation's login)"}
    if kind == "anthropic_api":
        key = sec("anthropic_api_key")
        if not key:
            raise ProviderError("No Anthropic API key is stored for the run's owner.")
        return {"kind": kind, "env": {"ANTHROPIC_API_KEY": key}, "model": model, "provider": "Anthropic API"}
    if kind == "enterprise":
        token = sec("enterprise_token")
        if not (token and s.get("base_url")):
            raise ProviderError("The enterprise endpoint is not set up for the run's owner.")
        return {"kind": kind, "env": {"ANTHROPIC_BASE_URL": s["base_url"], "ANTHROPIC_AUTH_TOKEN": token},
                "model": model, "provider": "Enterprise endpoint"}
    if kind == "litellm":
        options = {r["alias"]: r for r in routes_for(uid)} if uid else {}
        route = options.get(model) or options.get(s.get("route") or "") or (next(iter(options.values())) if options else None)
        if not route:
            raise ProviderError("No LiteLLM gateway route is available to the run's owner.")
        small = gateway_model(route.get("small") if route.get("small") in options else route["alias"])
        return {"kind": kind, "model": gateway_model(route["alias"]), "provider": f"{ROUTE_PROVIDERS[route['provider']]} via LiteLLM",
                "env": {"ANTHROPIC_BASE_URL": GATEWAY_URL, "ANTHROPIC_AUTH_TOKEN": gateway_token(uid, ttl_s + 600),
                        "ANTHROPIC_SMALL_FAST_MODEL": small, "ANTHROPIC_DEFAULT_HAIKU_MODEL": small}}
    if kind in CLI_KINDS:
        runner, secret, var, label = CLI_KINDS[kind]
        key = sec(secret)
        if not key and kind not in SHARED_LOGIN_KINDS:
            raise ProviderError(f"No API key is stored for {label} for the run's owner.")
        return {"kind": kind, "runner": runner, "env": {var: key} if key else {}, "model": s.get("cli_model") or "",
                "provider": label if key else f"{label} (this installation's Google login)"}
    raise ProviderError("Unknown provider.")


def backup_kind(uid: str | None) -> str | None:
    """The provider to try when the main one fails: the person's backup, else the policy's (mapped to a kind)."""
    s = settings(uid) if uid else {}
    if s.get("backup"):
        return s["backup"] if s["backup"] != s.get("kind") else None
    b = _policy().get("backup")
    kind = {"claude_account": "claude_account", "anthropic_api": "anthropic_api", "enterprise": "enterprise"}.get(b) \
        or ("litellm" if b in ("bedrock", "azure_foundry", "vertex") else None)
    return kind if kind and kind != s.get("kind", "claude_account") else None


def is_failover_error(text: str) -> bool:
    return bool(FAILOVER.search(text or ""))


CLI_DEFAULTS = {"codex": "the CLI's default model", "gemini": "the CLI's default model",
                "antigravity": "the CLI's default model"}


def cli_model_id(kind: str) -> str:
    """The picker's one entry for a CLI provider: the model itself comes from Settings › My AI provider."""
    return "cli:" + kind


def is_cli_model_id(model: str | None) -> bool:
    return bool(model) and str(model).startswith("cli:")


def catalog_for(uid: str | None, base: dict) -> dict:
    """The model picker: the person's gateway routes when they use LiteLLM, their CLI (Codex / Gemini / Antigravity)
    when they use one, else the Claude catalog."""
    s = settings(uid) if uid else {"kind": "claude_account"}
    if s["kind"] in CLI_KINDS:
        label = CLI_KINDS[s["kind"]][3]
        model = s.get("cli_model") or CLI_DEFAULTS[s["kind"]]
        entry = {"id": cli_model_id(s["kind"]), "label": f"{label} · {model}", "family": s["kind"], "latest": False,
                 "group": f"Your AI provider: {label}",
                 "note": f"Runs on {label} with {model} (set under Settings › My AI provider)."}
        return {"default": entry["id"], "models": [entry], "provider": s["kind"]}
    if s["kind"] != "litellm":
        return {**base, "provider": s["kind"]}
    models = [{"id": r["alias"], "label": f"{r['label']} · {ROUTE_PROVIDERS[r['provider']]}", "family": r["provider"],
               "latest": True} for r in routes_for(uid)]
    return {"default": s.get("route") or (models[0]["id"] if models else base["default"]), "models": models or base["models"],
            "provider": "litellm"}
