"""W2 Automation modules - what the packs share (n8n, rpa, idp, jobs and the Reports & alerts Migrate; docs/workbench.md).

  calls        one vendor call with the rules every W2 adapter keeps: 429 and 503 back off (Retry-After where the vendor
               sends it, exponential where it does not: Boomi, Google), other 5xx are retried, a 401 signs in again once
               (tokens expire), every other refusal is explained in words
  adapters     Connector SDK adapters (one adapter + one mock-lab simulator each) with a sign-in, the W2 reads (estate,
               runs, a run's detail) and writes that carry the approval's id in X-Relay-Approval; each registers its own
               connection kind (ids that no other wave uses: n8n_api, uipath_orchestrator, azure_di ...)
  estate       automations in one neutral shape - flows, bots and jobs with their trigger, steps, credentials by name -
               so an inventory, a finding or a conversion reads the same whatever the platform
  run history  runs in one shape: failure rate, the days a flow kept failing, slow runs
  diagnosis    a failure's own error text -> its cause, the change that cures it and who fixes it (rules first; the agent
               only where no rule fits)
  findings     secrets in clear, retire candidates, API candidates, expired sign-ins, flaky runs, no owner (rules)
  pushes       writes after their own approval (deploys, test runs, reruns) fed back to the step that asked (w2_pushes)
  tickets      a Service desk ticket raised through itsm.request_write - created only after its own itsm.write approval
  proofs       side_by_side (old and new on the same payloads), accuracy (a labelled set), cadence (next runs agree)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets as _secrets
import time
import traceback
from datetime import datetime, timezone

import httpx

from .. import auth, connectors, db, lineage, store
from .. import connectors_sdk as sdk
from .. import workbench as wb

MODULES = ("n8n", "rpa", "idp", "jobs", "schedule")
TIMEOUT = 30
BACKOFF_CAP_S = float(os.environ.get("W2_BACKOFF_CAP_S", "4"))
KINDS_ADDED = {"document": "Document", "process": "Process"}
lineage.NODE_KINDS = tuple(dict.fromkeys(tuple(lineage.NODE_KINDS) + tuple(KINDS_ADDED)))
for _k, _v in KINDS_ADDED.items():
    lineage.KIND_LABEL.setdefault(_k, _v)
EXTRA_EXT = (".xaml", ".nupkg", ".bprelease", ".jil", ".py", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bpmn", ".mp4", ".webm", ".tab", ".cron", ".log")
wb.DATA_EXT = tuple(dict.fromkeys(tuple(wb.DATA_EXT) + EXTRA_EXT))

db.register_schema("""
CREATE TABLE IF NOT EXISTS w2_pushes (
  approval TEXT PRIMARY KEY, module TEXT NOT NULL, item TEXT NOT NULL, step TEXT, connection TEXT, target TEXT, what TEXT, status TEXT NOT NULL,
  result TEXT NOT NULL DEFAULT '{}', created REAL NOT NULL, done REAL);
CREATE INDEX IF NOT EXISTS w2_pushes_item ON w2_pushes (item, step);
CREATE TABLE IF NOT EXISTS w2_fix_rules (
  id TEXT PRIMARY KEY, module TEXT NOT NULL, signature TEXT NOT NULL, cause TEXT, fix TEXT NOT NULL, learned_from TEXT, learned_by TEXT, applied INTEGER NOT NULL DEFAULT 1,
  created REAL NOT NULL, updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS w2_fix_rules_sig ON w2_fix_rules (module, signature);
""")

REFRESH: dict = {}             # "<module>.<work>.<step>" or "<module>.<step>" -> fn(ctx) -> the step's result, redrawn when a push lands


def j(s, default):
    try:
        return json.loads(s) if s else default
    except (TypeError, ValueError):
        return default


def slug(s, n: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:n] or "x"


def when(t) -> str:
    return time.strftime("%d %b %Y %H:%M UTC", time.gmtime(t)) if t else "-"


def epoch(v) -> float | None:
    """ISO 8601 (with Z, an offset or milliseconds), epoch seconds or milliseconds -> epoch seconds."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v) / (1000 if v > 1e11 else 1)
    s = str(v).strip()
    if re.fullmatch(r"\d{10,13}", s):
        return float(s) / (1000 if len(s) > 10 else 1)
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    except ValueError:
        pass
    for f in ("%Y/%m/%d %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y%m%d%H%M%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, f).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def iso(t: float | None) -> str | None:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


# ================================================================== vendor calls

class Expired(connectors.ConnectorError):
    """The platform refused the token: sign in again once, then give up with Reconsent."""


def call(label: str, method: str, url: str, *, headers: dict | None = None, json_body=None, params: dict | None = None, data=None, content: bytes | None = None,
         auth_=None, ok=(200, 201, 202, 204), attempts: int = 4, files=None) -> httpx.Response:
    """One vendor call: 429 / 503 back off (Retry-After when the vendor sends it, else 0.5 × 2^n seconds, capped), other
    5xx and dropped connections are retried, 401 raises Expired (the adapter signs in again once), a 403, 404 or any other
    refusal is explained with the vendor's own message."""
    last = ""
    for i in range(attempts):
        try:
            with httpx.Client(timeout=TIMEOUT, auth=auth_, headers={"Accept": "application/json", **(headers or {})}) as cl:
                r = cl.request(method, url, json=json_body, params=params, data=data, content=content, files=files)
        except httpx.TransportError as e:
            last = f"{label} could not be reached ({e.__class__.__name__})"
            time.sleep(min(BACKOFF_CAP_S, 0.25 * 2 ** i))
            continue
        if r.status_code == 401:
            raise Expired(f"{label} refused the sign-in (401): {_msg(r)[:200]}")
        if r.status_code in (429, 503) or r.status_code >= 500:
            last = f"{label} answered {r.status_code}: {_msg(r)[:160]}"
            ra = r.headers.get("Retry-After")
            try:
                wait_s = float(ra) if ra else 0.25 * 2 ** i
            except ValueError:
                wait_s = 1.0
            time.sleep(min(BACKOFF_CAP_S, wait_s))
            continue
        if r.status_code == 403:
            raise connectors.ConnectorError(f"{label} refused {method} {url.split('?')[0].rsplit('/', 1)[-1]} (403): {_msg(r)[:200]}")
        if r.status_code not in ok:
            raise connectors.ConnectorError(f"{label} refused {method} {url.split('?')[0]} ({r.status_code}): {_msg(r)[:300]}")
        return r
    raise connectors.ConnectorError(last or f"{label} did not answer")


def _msg(r: httpx.Response) -> str:
    try:
        b = r.json()
    except ValueError:
        return r.text[:300]
    if isinstance(b, dict):
        e = b.get("error")
        if isinstance(e, dict):
            return str(e.get("message") or e.get("code") or e)
        return str(b.get("message") or b.get("error_description") or e or b.get("errors") or b.get("detail") or b)[:300]
    return str(b)[:300]


def secret(c: dict, name: str) -> str:
    from .. import secrets_store
    v = secrets_store.get(f"user:{c['owner_id']}", f"conn:{c['id']}:{name}")
    if not v:
        raise connectors.Reconsent(f"No {name.replace('_', ' ')} is stored for {c['name']}: sign in again.")
    return v


def cfg(c: dict, key: str, default: str = "") -> str:
    return str((c.get("config") or {}).get(key) or default).strip()


class Adapter(sdk.Adapter):
    """A W2 platform: sign in, the reads every module needs, and writes after their approval. Subclasses set kind, label,
    fields, secrets and implement signin(c) -> headers, plus the reads / writes they support."""
    category = "integration"
    signin = ["api_key"]
    vendor = ""                 # what an error message calls it
    platform = ""               # the registry platform name it stands for ("n8n", "UiPath")
    simulator = ""              # tests/mocklab/sims/<file>: <id>

    def signin_headers(self, c: dict) -> dict:  # noqa: ARG002
        return {}

    def base(self, c: dict) -> str:
        return cfg(c, "base_url").rstrip("/")

    def req(self, c: dict, method: str, path: str, *, approval: str | None = None, headers: dict | None = None, ok=(200, 201, 202, 204), **kw) -> httpx.Response:
        """A signed-in call; a 401 signs in again once (an expired token), then asks the person to renew the sign-in."""
        url = path if path.startswith("http") else self.base(c) + path
        extra = {**(headers or {}), **({wb_approval_header(): approval} if approval else {})}
        for attempt in (0, 1):
            h = {**self.signin_headers(c), **extra}
            try:
                return call(self.vendor or self.label, method, url, headers=h, ok=ok, **kw)
            except Expired as e:
                if attempt:
                    raise connectors.Reconsent(f"{self.label} refused the stored sign-in twice: renew it under Connections. ({e})") from e
                self.forget(c)
        raise connectors.ConnectorError(f"{self.label} did not answer")

    def forget(self, c: dict) -> None:
        """Drop a cached token (the next signin_headers signs in again)."""

    # ---- what the W2 packs ask of a platform
    def estate(self, c: dict) -> list[dict]:  # noqa: ARG002
        return []

    def runs(self, c: dict, autos: list[dict], since: float | None = None) -> list[dict]:  # noqa: ARG002
        return []

    def test(self, c: dict) -> dict:
        a = self.estate(c)
        return {"ok": True, "sees": f"{len(a)} automation(s)", "scope": c.get("scope")}

    def list_objects(self, c: dict, search: str = "") -> list[dict]:
        return [{"object": a["id"], "type": f"{a['kind']}: {a['name']}"} for a in self.estate(c) if search.lower() in a["name"].lower()]

    def read(self, c: dict, obj: str, limit: int = 100) -> dict:
        a = next((x for x in self.estate(c) if x["id"] == obj), None)
        if not a:
            raise connectors.ConnectorError(f"{self.label} has no {obj!r}")
        rows = [{"step": s["label"], "kind": s["kind"], "system": s.get("system") or "", "api": s.get("api") or "", "screen": s.get("screen") or ""} for s in a["steps"]][:limit]
        return {"columns": ["step", "kind", "system", "api", "screen"], "rows": rows, "row_count": len(a["steps"])}

    def _write(self, c: dict, obj: str, payload: dict, approval: str) -> dict:
        """Every approved write lands here: do it, then tell the work item that asked (a refusal is recorded too)."""
        if "ops" in (payload or {}):                      # a Systems change (Integration & APIs) on this shared connection
            other = next((a for k, a in sdk.REGISTRY.items() if ALIAS.get(k) == self.kind and a is not self), None)
            if other is not None:
                return other._write(c, obj, payload, approval)
        try:
            out = self.write_now(c, obj, payload, approval)
        except Exception as e:
            push_written(approval, {"error": str(e)[:600]}, ok=False)
            raise
        push_written(approval, out, ok=bool(out.get("ok", True)))
        return out

    def write_now(self, c: dict, obj: str, payload: dict, approval: str) -> dict:  # noqa: ARG002
        raise sdk.ScopeError(f"{self.label}: Relay does not write {obj!r}")


def wb_approval_header() -> str:
    return "X-Relay-Approval"


ADAPTERS: dict[str, Adapter] = {}


def register(*adapters: Adapter) -> None:
    """One adapter per connection kind; the hub, the wizards and the readers find it through connectors.KINDS."""
    for a in adapters:
        ADAPTERS[a.kind] = a
        sdk.register(a)
        d = a.describe()
        connectors.KINDS[a.kind] = {"label": d["label"], "dialect": None, "auth": list(d["auth"]), "fields": [(f["key"], f["label"], f["required"]) for f in d["fields"]],
                                    "secrets": d["secrets"], "category": d["category"], "sdk": True}


# The same platform registered by two modules: Integration & APIs' Boomi and MuleSoft connections (kinds boomi,
# mulesoft) and Workflows' (boomi_atomsphere, mulesoft_anypoint) hold the same fields and secrets, so either works in
# both modules - reads through the module's own adapter, writes handed to the adapter that knows them.
ALIAS = {"boomi": "boomi_atomsphere", "mulesoft": "mulesoft_anypoint"}


def adapter(c: dict) -> Adapter | None:
    return ADAPTERS.get(c["kind"]) or ADAPTERS.get(ALIAS.get(c["kind"], ""))


# ================================================================== the neutral estate and run history

NEUTRAL = {"trigger": "Trigger", "read_mail": "Read e-mail", "extract": "Extract document fields", "lookup": "Look up a record", "decide": "Decision", "post": "Create or update a record",
           "human": "Hand to a person", "notify": "Notify", "validate": "Validate on a portal", "download": "Download a file", "loop": "For each item", "write": "Write a file",
           "export": "Export a report", "read_file": "Read a file", "type": "Type into a screen", "fetch": "Fetch records", "build": "Build a payload", "upload": "Upload a file",
           "code": "Code", "wait": "Wait", "http": "Call an API", "screen": "Screen step"}
API_SYSTEMS = {"Oracle Fusion", "SAP S/4HANA", "Entra ID", "Jira", "Power BI", "Zoho Books", "Workday", "Salesforce", "Dynamics 365"}   # systems with a documented API
SCREEN_ONLY = {"GST portal"}                                                                                                           # no API Relay can call


def auto(id_: str, name: str, platform: str, *, kind: str = "flow", active: bool = True, trigger: dict | None = None, steps: list | None = None, credentials: list | None = None,
         definition=None, owner: str | None = None, updated=None, schedule: str = "", **extra) -> dict:
    """One automation in the neutral shape every W2 pack reads."""
    steps = [dict(s, id=s.get("id") or f"s{i + 1}") for i, s in enumerate(steps or [])]
    return {"id": str(id_), "key": slug(name, 60), "name": name, "platform": platform, "kind": kind, "active": bool(active), "trigger": trigger or {"kind": "manual", "detail": ""},
            "steps": steps, "credentials": sorted(set(credentials or [])), "definition": definition, "owner": owner, "updated": updated, "schedule": schedule,
            "secrets": secrets_in(definition), **extra}


def step(label: str, kind: str, *, system: str = "", api: str = "", screen: str = "", field: str = "", detail: str = "", sid: str = "") -> dict:
    return {"id": sid, "label": label, "kind": kind if kind in NEUTRAL else "http", "system": system, "api": api, "screen": screen, "field": field, "detail": detail}


def run(id_: str, target: str, status: str, start, end=None, error: str | None = None, node: str | None = None, items=None, **extra) -> dict:
    st = {"succeeded": "success", "success": "success", "successful": "success", "complete": "success", "completed": "success", "ok": "success",
          "failed": "failed", "error": "failed", "errored": "failed", "faulted": "failed", "failure": "failed", "terminated": "failed",
          "running": "running", "queued": "queued", "pending": "queued", "new": "queued", "cancelled": "cancelled", "canceled": "cancelled", "stopped": "cancelled"}.get(str(status).lower(), str(status).lower())
    return {"id": str(id_), "target": str(target), "status": st, "start": epoch(start), "end": epoch(end), "error": error or None, "node": node, "items": items, **extra}


SECRET_KEY = re.compile(r"(pass(word|wd)?|pwd|secret|api[_-]?key|token|basic_auth|client_secret)$", re.I)
SECRET_INLINE = re.compile(r"(pass(word|wd)?|pwd|secret)\s*[=:]\s*['\"]?([^\s'\"<>{}]{6,})", re.I)


def secrets_in(defn) -> list[dict]:
    """Literal credentials kept in a definition (a variable, an asset of type Text, a property, a parameter) - never an
    expression, a credential reference or a vault lookup. Returns where each is, never the value."""
    out: list[dict] = []

    def literal(v) -> bool:
        s = str(v or "").strip()
        return bool(s) and len(s) >= 6 and not s.startswith(("=", "{{", "@", "#[", "$", "${", "<")) and not re.fullmatch(r"\*+|x+|<[^>]+>|null|none|true|false", s, re.I)

    def walk(o, path):
        if isinstance(o, dict):
            nm = str(o.get("name") or o.get("Name") or o.get("key") or "")
            if nm and SECRET_KEY.search(nm) and literal(o.get("value") if "value" in o else o.get("Value") if "Value" in o else o.get("default")):
                out.append({"where": path + f" > {nm}", "kind": "a named value"})
            for k, v in o.items():
                if isinstance(v, (str, int, float)) and SECRET_KEY.search(str(k)) and literal(v) and str(k).lower() not in ("passwordref", "token_url"):
                    out.append({"where": path + f" > {k}", "kind": "a parameter"})
                elif isinstance(v, (dict, list)):
                    walk(v, path + f" > {k}")
                elif isinstance(v, str) and ("|" in v or "=" in v) and SECRET_INLINE.search(v):
                    out.append({"where": path + f" > {k}", "kind": "inline"})
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, path + f"[{i}]")
        elif isinstance(o, str) and SECRET_INLINE.search(o):
            out.append({"where": path, "kind": "inline text"})
    if isinstance(defn, str):
        for m in re.finditer(r'<(?:[\w:]*)?(?:global-property|processproperty|variable|Variable|stage)\b[^>]*name="([^"]*)"[^>]*value="([^"]*)"', defn):
            if SECRET_KEY.search(m.group(1).split(".")[-1]) and literal(m.group(2)):
                out.append({"where": f"property {m.group(1)}", "kind": "a property"})
        for m in re.finditer(r'<(?:\w+:)?(?:Variable|InArgument|Argument)\b[^>]*Name="([^"]*)"[^>]*Default="([^"]*)"', defn):
            if SECRET_KEY.search(m.group(1)) and literal(m.group(2)):
                out.append({"where": f"variable {m.group(1)}", "kind": "a default value"})
    else:
        walk(defn, "definition")
    seen, uniq = set(), []
    for x in out:
        if x["where"] not in seen:
            seen.add(x["where"])
            uniq.append(x)
    return uniq


def history(runs: list[dict], target: str, now: float | None = None) -> dict:
    """What a flow's runs say: count, failures, the failure rate, the days it kept failing to now, the last error and
    its step, the last success, the median duration."""
    now = now or wb.lab_now()
    rs = sorted([r for r in runs if r["target"] == target and r.get("start")], key=lambda r: r["start"])
    done = [r for r in rs if r["status"] in ("success", "failed")]
    fails = [r for r in done if r["status"] == "failed"]
    streak = 0.0
    for r in reversed(done):
        if r["status"] != "failed":
            break
        streak = (now - r["start"]) / 86400
    durs = sorted((r["end"] - r["start"]) for r in done if r.get("end") and r.get("start") and r["end"] >= r["start"])
    last_ok = max((r["start"] for r in done if r["status"] == "success"), default=None)
    lf = fails[-1] if fails else None
    return {"runs": len(done), "failed": len(fails), "rate": round(len(fails) / len(done), 3) if done else 0.0, "failing_days": round(streak, 1) if done and done[-1]["status"] == "failed" else 0.0,
            "last_error": lf.get("error") if lf else None, "last_node": lf.get("node") if lf else None, "last_failed_run": lf["id"] if lf else None,
            "last_success": last_ok, "last_run": done[-1]["start"] if done else None, "median_s": durs[len(durs) // 2] if durs else None,
            "items": max((r.get("items") or 0) for r in done) if done else 0}


# ================================================================== diagnosis: the error's own words -> cause, cure, route

DIAGNOSES = [
    # (signature, regex, cause, fix kind, the cure in plain words, route: change | heal | person | rerun)
    ("payload_schema", r"GSTR-?1 v1 schema|GSTR1_V1|schema is no longer accepted|schema version",
     "The receiving system changed the schema it accepts: GSTR-1 v1 is refused and GSTR1_V2 is expected.", "change_payload",
     "Change the upload's payload so it sends GSTR1_V2 (the step's body), test it, then deploy the changed definition.", "change"),
    ("credential_expired", r"AADSTS7000222|client secret keys?.*expired|secret .*expired|connection .* not (valid|authori[sz]ed)|authori[sz]ation (failed|expired)",
     "The sign-in the flow uses has expired (the identity app's client secret), so every run since fails with 401.", "rotate_credential",
     "Renew the secret in the platform's credential store, point the step at the renewed credential (by name), then re-run the failed runs.", "heal"),
    ("screen_changed", r"[Ss]elector not found|element .* not found|UI ?element|could not find (the )?element|[Ff]ailed to find element|[Rr]ecorder: object not found|ElementNotFound|upload page|SelectorNotFound|Target (element|window) .*not",
     "The screen the bot works on changed (a selector no longer finds its element).", "update_selector",
     "Update the selector (or, where the system has an API, call it instead of the screen), test it on the new screen, then deploy.", "change"),
    ("transient", r"[Tt]ime ?out|timed out|did not answer|temporarily|unavailable|\b50[234]\b|throttl|429|connection reset",
     "A transient failure (a timeout or a short outage), not the flow's logic or data.", "rerun", "Run it again; if it repeats, look at the system it waits for.", "rerun"),
    ("business_exception", r"[Bb]usiness exception|confidence [0-9.]+ below|sent to .* (queue|review)|low[- ]confidence",
     "Not a fault: a business exception that the flow hands to a person by design (a low-confidence document).", "none",
     "Nothing to fix in the flow; if the share grows, look at the documents (Document processing) or the threshold.", "person"),
    ("credential_401", r"\b401\b|[Uu]nauthori[sz]ed|invalid_client|access token",
     "The platform or a system it calls refused the sign-in.", "rotate_credential", "Renew the credential by name in the platform, then re-run.", "heal"),
    ("missing_column", r"CURRENCY_CODE|invalid identifier|column .* (not found|does not exist)|no such column",
     "A source column the job reads was renamed (CURRENCY_CODE is now CURRENCY).", "change_parameter",
     "Stop passing the old column (SRC_CURRENCY_COLUMN=CURRENCY_CODE), deploy the definition, then rerun the job.", "change"),
]


def diagnose(error: str | None) -> dict:
    """Rules first: the first signature whose words are in the error. Unknown errors say so (the agent may be asked)."""
    text = str(error or "")
    for sig, rx, cause, fix, cure, route in DIAGNOSES:
        if re.search(rx, text):
            return {"signature": sig, "cause": cause, "fix": fix, "cure": cure, "route": route, "matched": True}
    return {"signature": "unknown", "cause": "No rule knows this error yet: ask Relay to diagnose it, or read the run's log.", "fix": "unknown",
            "cure": "A person (or Relay's agent) reads the log and names the change.", "route": "heal", "matched": False}


def learned_fix(module: str, signature: str) -> dict | None:
    r = db.one("SELECT * FROM w2_fix_rules WHERE module = ? AND signature = ? ORDER BY updated DESC LIMIT 1", (module, signature))
    return {**r, "fix": j(r["fix"], {})} if r else None


def learn_fix(ctx: wb.Ctx, signature: str, cause: str, fix: dict) -> dict:
    """The fix becomes a rule: the next failure with the same signature starts from it."""
    now = time.time()
    have = learned_fix(ctx.module, signature)
    if have:
        db.run("UPDATE w2_fix_rules SET fix = ?, cause = ?, applied = applied + 1, learned_from = ?, learned_by = ?, updated = ? WHERE id = ?",
               (json.dumps(fix), cause, ctx.id, ctx.who or ctx.owner, now, have["id"]))
        rid = have["id"]
    else:
        rid = "w2r-" + _secrets.token_hex(4)
        db.run("INSERT INTO w2_fix_rules (id, module, signature, cause, fix, learned_from, learned_by, applied, created, updated) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
               (rid, ctx.module, signature, cause, json.dumps(fix), ctx.id, ctx.who or ctx.owner, now, now))
    db.audit("w2.rule.learned", rid, {"module": ctx.module, "signature": signature, "item": ctx.id}, ctx.who or ctx.owner)
    return learned_fix(ctx.module, signature) or {}


# ================================================================== findings by rules

def findings(autos: list[dict], runs: list[dict], now: float | None = None, *, screen_rows: int = 200) -> list[dict]:
    """What the estate shows, rule by rule: each finding says what, where, how bad and what to do."""
    now = now or wb.lab_now()
    out = []
    for a in autos:
        h = history(runs, a["id"], now)
        where = f"{a['name']} ({a.get('platform_label') or a['platform']})"

        def add(kind, sev, what, do, **x):
            out.append({"id": f"{kind}-{slug(a['platform'], 16)}-{slug(a['id'], 40)}", "auto": a["id"], "flow": a["name"], "platform": a.get("platform_label") or a["platform"], "kind": kind,
                        "severity": sev, "what": what, "do": do, "decision": "keep", **x})
        for s in a.get("secrets") or []:
            add("secret", "high", f"A credential is kept in clear in {s['where']} ({s['kind']})", "move it to the platform's credential store and refer to it by name")
            break
        if h["failing_days"] >= 1 and h["failed"]:
            d = diagnose(h["last_error"])
            add("failing", "high", f"Every run has failed for {h['failing_days']:g} day(s): {str(h['last_error'] or '')[:160]}", d["cure"], signature=d["signature"], error=h["last_error"],
                node=h["last_node"], run=h["last_failed_run"])
        elif h["runs"] >= 5 and h["rate"] >= 0.1:
            d = diagnose(h["last_error"])
            add("flaky" if d["signature"] != "business_exception" else "exceptions", "medium", f"{h['failed']} of {h['runs']} runs failed ({h['rate']:.0%}); last: {str(h['last_error'] or '')[:140]}",
                d["cure"], signature=d["signature"], error=h["last_error"])
        if not a["active"] and (h["last_success"] is None or now - h["last_success"] > 60 * 86400):
            age = f"{(now - h['last_success']) / 86400:.0f} days" if h["last_success"] else "ever"
            add("retire", "medium", f"Switched off; no successful run for {age}", "retire it (or confirm someone still needs it)")
        exc = sum(1 for r in runs if r["target"] == a["id"] and r["status"] == "success" and r.get("business_exception"))
        if exc and h["runs"] and exc / h["runs"] >= 0.05:
            add("exceptions", "low", f"{exc} of {h['runs']} runs sent work to a person (business exceptions)", "look at the documents and the confidence threshold (Document processing)")
        typed = [s for s in a["steps"] if s["kind"] in ("type", "screen") or (s.get("screen") and not s.get("api"))]
        api_ok = [s for s in typed if s.get("system") in API_SYSTEMS]
        if api_ok:
            add("api_candidate", "medium" if h["items"] >= screen_rows else "low",
                f"{len(api_ok)} screen step(s) on {', '.join(sorted({s['system'] for s in api_ok}))}, which has an API" + (f"; {h['items']} rows typed per run" if h["items"] >= screen_rows else ""),
                "call the system's API instead of the screen", steps=[s["label"] for s in api_ok])
        if h["median_s"] and h["median_s"] > 600:
            add("slow", "low", f"A run takes {h['median_s'] / 60:.0f} minutes (median)", "see what it waits for; an API call is usually faster than a screen")
        if not a.get("owner"):
            add("no_owner", "low", "No owner is named", "name the person or team who owns it")
    return out


# ================================================================== pushes: writes after their per-change approval, fed back

def request_push(ctx: wb.Ctx, connection_id: str, obj: str, payload: dict, what: str, *, step: str | None = None, items: list[str] | None = None, meta: dict | None = None) -> dict:
    """ctx.request_write with what the approver reads in plain words and the link back to the step: a connection.write
    checkpoint - the adapter writes when, and only when, a named person accepts exactly this. An older request of the
    same step on the same connection that nobody decided yet is withdrawn (it asked for something that changed); `meta`
    is kept with the push (what was asked for, e.g. the hash of the workflow tested)."""
    sid = step or ctx.step_id
    payload = {"from": f"{ctx.module}:{ctx.id}:{sid}", **payload}
    c = ctx.connection(connection_id)
    link = wb.route_of(ctx.st) + f"?step={sid}"
    for old in db.q("SELECT approval FROM w2_pushes WHERE item = ? AND step = ? AND connection = ? AND status = 'awaiting'", (ctx.id, sid, connection_id)):
        db.run("UPDATE checkpoints SET status = 'withdrawn', decided = ?, decided_by = 'system' WHERE id = ? AND status = 'open'", (time.time(), old["approval"]))
        db.run("UPDATE w2_pushes SET status = 'withdrawn', done = ? WHERE approval = ?", (time.time(), old["approval"]))
    try:
        cp = connectors.request_write(c, obj, payload, ctx.who or ctx.owner, module=ctx.module_name, what=what, items=items, link=link)
    except Exception as e:  # noqa: BLE001 - ScopeError / ConnectorError: shown to the person
        raise wb.StepFailed(str(e)) from e
    ctx._handoff({"kind": "write", "label": what, "connection": c["name"], "checkpoint": cp["id"], "status": "awaiting approval", "link": "#/validate"})
    db.run("INSERT OR REPLACE INTO w2_pushes (approval, module, item, step, connection, target, what, status, result, created) VALUES (?, ?, ?, ?, ?, ?, ?, 'awaiting', ?, ?)",
           (cp["id"], ctx.module, ctx.id, sid, connection_id, c["kind"], what[:300], json.dumps(meta or {}, default=str), time.time()))
    return cp


def pushes(item: str, step: str | None = None) -> list[dict]:
    rows = db.q("SELECT * FROM w2_pushes WHERE item = ? AND status != 'withdrawn'" + (" AND step = ?" if step else "") + " ORDER BY created", (item, step) if step else (item,))
    return [{**r, "result": j(r["result"], {})} for r in rows]


def push_of(item: str, step: str) -> dict | None:
    ps = pushes(item, step)
    return ps[-1] if ps else None


def push_written(approval: str, result: dict, ok: bool = True) -> None:
    """Called by an adapter after it wrote (or failed to write) what a person approved."""
    r = db.one("SELECT * FROM w2_pushes WHERE approval = ?", (approval,))
    if not r:
        return
    result = {**j(r["result"], {}), **(result or {})}
    db.run("UPDATE w2_pushes SET status = ?, result = ?, done = ? WHERE approval = ?", ("written" if ok else "failed", json.dumps(result, default=str)[:400000], time.time(), approval))
    try:
        store.log(r["item"], {"kind": "agent", "text": f"{r['what']}: " + ("done" if ok else "failed - " + str(result.get("error") or "")[:200])})
    except (KeyError, FileNotFoundError):
        return
    apply_refresh(r["item"], r["step"])


def _refused(cp: dict, event: str, result) -> None:
    """The connection write was sent back (refused) or failed before the adapter ran: the step says so."""
    if event == "written":
        return
    r = db.one("SELECT * FROM w2_pushes WHERE approval = ?", (cp["id"],))
    if not r or r["status"] != "awaiting":
        return
    db.run("UPDATE w2_pushes SET status = ?, result = ?, done = ? WHERE approval = ?", ("refused" if event == "sent_back" else "failed", json.dumps({"error": str(result or event)[:400]}), time.time(), cp["id"]))
    apply_refresh(r["item"], r["step"])


for _m in MODULES:
    connectors.register_write_hook(_m, _refused)


def push_problems(item: str, step: str) -> list[str]:
    p = push_of(item, step)
    if not p:
        return []
    if p["status"] == "awaiting":
        return [f"Nothing is done yet: accept \"{p['what']}\" in the Validation queue (its own approval), then confirm here"]
    if p["status"] in ("failed", "refused"):
        return [f"\"{p['what']}\" was {'refused' if p['status'] == 'refused' else 'not done'} ({str(p['result'].get('error') or '')[:160]}) - run the step again"]
    return []


def apply_refresh(item: str, step: str) -> None:
    """Redraw a step from what changed outside it (a push landed); the journey does not move."""
    try:
        st = wb._load(item)
    except (KeyError, FileNotFoundError, ValueError):
        return
    fn = REFRESH.get(f"{st['module']}.{st['work']}.{step}") or REFRESH.get(f"{st['module']}.{step}")
    if not fn:
        return
    try:
        ctx = wb.Ctx(item, step)
        out = wb._normalise(fn(ctx))
    except Exception:  # noqa: BLE001 - the write's own outcome is recorded either way
        traceback.print_exc()
        return

    def f(s):
        x = wb._step(s, step)
        new_ev = [e["id"] for e in ctx.new_evidence]
        wb._save_ctx(ctx, s)
        x["evidence"] = ((x.get("evidence") or []) + new_ev)[-80:]
        x["outputs"] = sorted({o["name"] for o in s["outputs"] if o.get("step") == step})
        x.update(summary=out["summary"] or x.get("summary") or "", counts=out["counts"] or x.get("counts") or {}, items=out["items"] or x.get("items") or [])
        if out["data"] is not None:
            x["data"] = out["data"]
        if out["records"] is not None:
            x["records"] = wb._ids(out["records"])
    wb._mutate(item, f)


# ================================================================== Service desk tickets (create after its own approval)

def desk_sources() -> list[dict]:
    try:
        from .. import itsm
    except Exception:  # noqa: BLE001
        return []
    out = []
    for s in db.q("SELECT * FROM itsm_sources WHERE paused = 0 ORDER BY created"):
        if itsm.may(s, "create"):
            out.append({"id": s["id"], "name": s["name"], "kind": s["kind"]})
    return out


def desk_options(u: dict) -> list[tuple[str, str]]:  # noqa: ARG001
    return [("", "None - a ticket draft in the outputs")] + [(s["id"], f"{s['name']} ({s['kind']})") for s in desk_sources()]


def desk_ticket(ctx: wb.Ctx, source_id: str, title: str, body: str, *, priority: str = "P3", ref: str = "") -> dict:
    """One ticket through the Service desk (P12): itsm.request_write opens its itsm.write checkpoint with exactly what
    is written; nothing is created before a named person accepts it. Without a source, the engine's ticket hand-off
    (a matching Service desk group, else a draft in the outputs)."""
    if not source_id:
        return ctx.ticket(title, body, priority=priority, about=title)
    from .. import itsm
    who = ctx.who or ctx.owner
    try:
        wr = itsm.request_write(source_id, "create", {"title": title[:250], "description": body[:7000], "priority": priority, "labels": ["relay", ctx.module]},
                                who=who, module=ctx.module_name, origin=f"{ctx.module}:{ctx.id}:{ctx.step_id}:{ref or slug(title)}", link=wb.route_of(ctx.st) + f"?step={ctx.step_id}",
                                assignee=who, name=f"Raise a ticket: {title}"[:200])
    except Exception as e:  # noqa: BLE001 - WriteRefused / ItsmError: the reason is shown
        raise wb.StepFailed(str(e)) from e
    db.run("INSERT OR REPLACE INTO w2_pushes (approval, module, item, step, connection, target, what, status, result, created) VALUES (?, ?, ?, ?, ?, 'itsm', ?, 'awaiting', ?, ?)",
           (wr["id"], ctx.module, ctx.id, ctx.step_id, source_id, f"Raise a ticket: {title}"[:300], json.dumps({"ref": ref}), time.time()))
    return ctx._handoff({"kind": "ticket", "label": title, "checkpoint": wr.get("checkpoint_id"), "status": "awaiting the write approval", "link": "#/validate", "via": wr.get("source")})


def _desk_hook(wr: dict, event: str) -> None:
    res = wr.get("result") or {}
    ok = event == "written"
    db.run("UPDATE w2_pushes SET status = ?, result = ?, done = ? WHERE approval = ?",
           ("written" if ok else "failed", json.dumps({"key": res.get("key"), "url": res.get("url")} if ok else {"error": wr.get("error") or event}), time.time(), wr["id"]))
    parts = str(wr.get("origin") or "").split(":")
    if len(parts) >= 3:
        try:
            store.log(parts[1], {"kind": "agent", "text": f"{wr.get('title')}: " + (f"raised ({res.get('key') or 'ticket'})" if ok else f"not raised - {event}")})
        except (KeyError, FileNotFoundError):
            pass


try:
    from .. import itsm as _itsm
    for _m in MODULES:
        _itsm.register_write_hook(_m, _desk_hook)
except Exception:  # noqa: BLE001 - without the Service desk, tickets are drafts
    pass


# ================================================================== proofs every W2 pack uses

@wb.proof("side_by_side", "Old and new, side by side on the same payloads")
def _p_side(ctx: wb.Ctx, pairs: list[dict], **_):  # noqa: ARG001
    """pairs: [{"case", "old": {"status", "detail"}, "new": {"status", "detail"}, "expected"?: "why a difference is expected"}]."""
    rows, bad, expected = [], 0, 0
    for p in pairs:
        o, n = (p.get("old") or {}).get("status"), (p.get("new") or {}).get("status")
        same = o == n
        why = p.get("expected") or ""
        if not same and why:
            expected += 1
        elif not same:
            bad += 1
        rows.append({"case": p.get("case"), "old": o, "new": n, "same": same, "why": why or ("" if same else "unexpected"), "old_detail": (p.get("old") or {}).get("detail"),
                     "new_detail": (p.get("new") or {}).get("detail")})
    n = len(rows)
    status = "fail" if bad or not n else "warn" if expected else "pass"
    return {"status": status, "measured": n - bad - expected, "expected": n, "rows": rows,
            "detail": (f"{n - bad - expected} of {n} case(s) behave the same" + (f"; {expected} differ as decided" if expected else "") + (f"; {bad} differ unexpectedly" if bad else "")) if n else "nothing was run side by side"}


@wb.proof("accuracy", "Accuracy against the labelled set")
def _p_accuracy(ctx: wb.Ctx, rows: list[dict], min_pct: float = 95.0, label: str = "", **_):  # noqa: ARG001
    """rows: [{"doc", "field", "expected", "got", "ok"}] - field-level accuracy against a person's labels."""
    n = len(rows)
    good = sum(1 for r in rows if r.get("ok"))
    pct = round(100.0 * good / n, 1) if n else 0.0
    return {"status": "pass" if n and pct >= min_pct else "fail", "measured": f"{pct} %", "expected": f"at least {min_pct:g} %", "rows": [r for r in rows if not r.get("ok")][:200] or rows[:50],
            "detail": f"{good} of {n} labelled field(s) right ({pct} %)" + (f" - {label}" if label else "")}


@wb.proof("cadence", "The new schedule fires when the old one did")
def _p_cadence(ctx: wb.Ctx, pairs: list[dict], **_):  # noqa: ARG001
    """pairs: [{"case", "old": [epoch ...], "new": [epoch ...], "tolerance_s"}] - the next fire times on both sides."""
    rows, bad = [], 0
    for p in pairs:
        o, n = [round(x) for x in p.get("old") or []], [round(x) for x in p.get("new") or []]
        tol = float(p.get("tolerance_s") or 60)
        same = len(o) == len(n) and all(abs(a - b) <= tol for a, b in zip(o, n))
        bad += 0 if same else 1
        rows.append({"case": p.get("case"), "old": [iso(x) for x in o], "new": [iso(x) for x in n], "same": same})
    return {"status": "pass" if rows and not bad else "fail", "measured": len(rows) - bad, "expected": len(rows), "rows": rows,
            "detail": f"{len(rows) - bad} of {len(rows)} schedule(s) fire at the same times" + (f"; {bad} differ" if bad else "")}


# ================================================================== small things every W2 pack needs

def table(columns: list[str], rows: list[list]) -> dict:
    return {"columns": columns, "rows": rows}


def gates(rows: list[dict]) -> dict:
    return {"checks": rows}


def gate(name: str, label: str, status: str, measured="", expected="", detail="", severity: str | None = None, evidence: str | None = None) -> dict:
    g = {"name": name, "label": label, "status": status, "measured": measured, "expected": expected, "detail": detail}
    if severity:
        g["severity"] = severity
    if evidence:
        g["evidence"] = evidence
    return g


def sha(data) -> str:
    return hashlib.sha256(data if isinstance(data, bytes) else json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def visible_items(u: dict, rows: list[dict], key: str = "item") -> list[dict]:
    ids = [r[key] for r in rows if r.get(key)]
    vis = auth.access_map(u, ids)
    return [r for r in rows if not r.get(key) or r[key] in vis]


def connections_of(ctx: wb.Ctx, kinds: tuple | None = None) -> list[dict]:
    return [c for c in ctx.connections() if c["kind"] in ADAPTERS and (not kinds or c["kind"] in kinds)]


def read_estate(ctx: wb.Ctx, kinds: tuple | None = None, *, with_runs: bool = True, since_days: int = 30) -> tuple[list[dict], list[dict], list[dict]]:
    """Every connected platform of these kinds, read-only: (automations, runs, what each source answered)."""
    autos, runs, answered = [], [], []
    for c in connections_of(ctx, kinds):
        a = adapter(c)
        try:
            got = a.estate(c)
            for x in got:
                x["connection"], x["platform_label"] = c["id"], a.label
            rs = a.runs(c, got, wb.lab_now() - since_days * 86400) if with_runs else []
            autos += got
            runs += rs
            answered.append({"source": c["name"], "kind": a.label, "ok": True, "sees": f"{len(got)} automation(s), {len(rs)} run(s)", "connection": c["id"]})
        except connectors.Reconsent as e:
            answered.append({"source": c["name"], "kind": a.label, "ok": False, "sees": f"sign in again: {e}"[:300], "connection": c["id"]})
        except (connectors.ConnectorError, sdk.ScopeError) as e:
            answered.append({"source": c["name"], "kind": a.label, "ok": False, "sees": str(e)[:300], "connection": c["id"]})
    return autos, runs, answered


def lineage_auto(ctx: wb.Ctx, a: dict, *, kind: str = "flow", own: bool = False) -> str:
    """A flow, bot or job in the lineage graph (shared with Integration analytics and Self-healing), with the systems
    its steps read and write."""
    nid = ctx.lineage_node(kind, a.get("platform_label") or a["platform"], a["name"], label=f"{a['name']} ({a.get('platform_label') or a['platform']})", own=own,
                           properties={"platform": a["platform"], "id": a["id"], "steps": len(a.get("steps") or [])})
    for s in a.get("steps") or []:
        if s.get("system"):
            sn = ctx.lineage_node("system", s["system"], s["system"], label=s["system"], own=False)
            ctx.lineage_edge(nid, sn, "writes" if s["kind"] in ("post", "upload", "type", "write") else "reads" if s["kind"] in ("lookup", "fetch", "download", "read_file", "read_mail") else "calls",
                             {"step": s["label"]})
    return nid
