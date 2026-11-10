"""W3 Systems — the kit every Systems pack shares (ERP, finance & accounting, CRM, HR & payroll, identity & access,
integration & APIs, collaboration & content, PLM, cloud & CI/CD, apps & products). Not a pack itself (the leading
underscore keeps app/packs/__init__.py from importing it as one); each W3 pack imports it.

What it gives a pack:
  Api          one signed-in session to a platform for one connection: the vendor's sign-in (by the adapter), signed in
               again once when the token expired, backs off on throttles (Retry-After, else exponential), and every
               write carries X-Relay-Approval — the id of the checkpoint a named person accepted.
  SysAdapter   a Connector SDK adapter (one per platform) that reads canonical records (customer, supplier, product,
               order, invoice, account, worker, user, part …) out of the vendor's own objects, lists its job runs, and
               writes only through connectors.request_write (scope + a per-change approval).
  register()   the adapter joins the SDK registry and the Connections hub (connectors.KINDS) at import.
  Spec + the five journeys (assess / develop / change / migrate / run): rules first, a person confirms every step
               that matters, writes only after a per-change approval, record reconciliation as the proof.
Everything a step reads lands in the item's folder (data/*.csv snapshots, evidence/, outputs/), so every number is
one click away and the built-in proofs (row counts, checksums, totals, sample diffs) reconcile files with DuckDB.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets as _secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import httpx

from .. import connectors, db, registry
from .. import connectors_sdk as sdk
from .. import workbench as wb

APPROVAL = "X-Relay-Approval"
TIMEOUT = float(os.environ.get("W3_HTTP_TIMEOUT_S", "30"))
RETRY_CAP = float(os.environ.get("W3_RETRY_CAP_S", "8"))
UPLOADS = (".csv", ".xlsx", ".txt", ".json", ".xml")

db.register_schema("""
CREATE TABLE IF NOT EXISTS w3_rules (
  id TEXT PRIMARY KEY, module TEXT NOT NULL, signature TEXT NOT NULL, cause TEXT NOT NULL, fix TEXT NOT NULL, ops TEXT NOT NULL DEFAULT '[]',
  learned_from TEXT, learned_by TEXT, uses INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS w3_rules_module ON w3_rules (module);
""")


# ================================================================== the HTTP session

class Api:
    """One signed-in session to one connection's platform (made per step, closed when the step ends)."""

    def __init__(self, adapter: "SysAdapter", c: dict):
        self.a, self.c = adapter, c
        self.cfg = c.get("config") or {}
        self.base = adapter.base(c).rstrip("/")
        self.headers: dict | None = None
        self.cookies: dict = {}
        self.state: dict = {}                     # what a sign-in keeps (a CSRF token, a session id, a uid)
        self.calls = 0
        self.http = httpx.Client(timeout=TIMEOUT, follow_redirects=False)

    def close(self) -> None:
        try:
            self.http.close()
        except Exception:  # noqa: BLE001
            pass

    def secret(self, name: str) -> str:
        v = connectors._secret(self.c, name)
        if not v:
            raise connectors.Reconsent(f"No {name.replace('_', ' ')} is stored for {self.c['name']}. Renew the connection.")
        return v

    def url(self, path: str) -> str:
        return path if path.startswith(("http://", "https://")) else self.base + ("" if path.startswith("/") else "/") + path

    def raw(self, method: str, path: str, **kw) -> httpx.Response:
        """A call without the session's sign-in headers (the sign-in itself)."""
        h = dict(kw.pop("headers", None) or {})
        if self.cookies:
            h.setdefault("Cookie", "; ".join(f"{k}={v}" for k, v in self.cookies.items()))
        try:
            r = self.http.request(method, self.url(path), headers=h, **kw)
        except httpx.HTTPError as e:
            raise connectors.ConnectorError(f"{self.a.label} did not answer ({e.__class__.__name__}).") from e
        self.calls += 1
        self._take_cookies(r)
        return r

    def _take_cookies(self, r: httpx.Response) -> None:
        """Session cookies kept by hand: a lab URL is plain http, and a `secure` cookie (SAP's) would not come back."""
        for v in r.headers.get_list("set-cookie"):
            name, _, val = v.split(";", 1)[0].partition("=")
            if name.strip():
                self.cookies[name.strip()] = val.strip()
        self.http.cookies.clear()

    def request(self, method: str, path: str, *, params=None, json=None, data=None, content=None, headers=None, approval: str | None = None,
                signed: bool = True) -> httpx.Response:
        method = method.upper()
        again = False
        r = None
        for attempt in range(6):
            h = dict(headers or {})
            if signed:
                if self.headers is None:
                    self.headers = self.a.sign_in(self) or {}
                h = {**self.headers, **h}
            if self.cookies:
                h.setdefault("Cookie", "; ".join(f"{k}={v}" for k, v in self.cookies.items()))
            if approval:
                h[APPROVAL] = approval
            try:
                r = self.http.request(method, self.url(path), params=params, json=json, data=data, content=content, headers=h)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                if method == "GET" and attempt < 2:
                    time.sleep(min(RETRY_CAP, 0.5 * 2 ** attempt))
                    continue
                raise connectors.ConnectorError(f"{self.a.label} did not answer ({e.__class__.__name__}).") from e
            self.calls += 1
            self._take_cookies(r)
            if signed and not again and self.a.expired(r):
                self.headers, self.cookies, again = None, {}, True        # sign in again once
                self.a.on_expired(self)
                continue
            if r.status_code == 429 or (method == "GET" and r.status_code in (502, 503, 504)) or self.a.throttled(r):
                if attempt < 5:
                    time.sleep(min(RETRY_CAP, self.a.retry_after(r) or 0.5 * 2 ** attempt))
                    continue
            return r
        return r

    def json(self, method: str, path: str, *, what: str = "", ok: tuple = (200, 201, 202, 204), **kw):
        r = self.request(method, path, **kw)
        return self.a.check(r, what or path, ok)

    def get(self, path: str, params=None, **kw):
        return self.json("GET", path, params=params, **kw)


# ================================================================== canonical records

ENTITY = {   # canonical entity -> (label (plural), the fields every adapter maps to, in order)
    "customer": ("customers", ["key", "number", "name", "email", "country", "city", "currency", "tax_id", "credit_limit", "group", "status", "created"]),
    "supplier": ("suppliers", ["key", "number", "name", "email", "country", "currency", "terms", "status"]),
    "product": ("products", ["key", "sku", "name", "category", "uom", "price", "status"]),
    "order": ("sales orders", ["key", "number", "customer", "date", "currency", "amount", "status"]),
    "invoice": ("invoices", ["key", "number", "party", "date", "currency", "amount", "tax", "status", "place_of_supply", "gstin"]),
    "account": ("ledger accounts", ["key", "name", "group", "type", "debit", "credit", "balance"]),
    "voucher": ("voucher lines", ["key", "number", "date", "type", "account", "debit", "credit"]),
    "worker": ("workers", ["key", "number", "name", "email", "department", "country", "status", "end_date", "manager"]),
    "user": ("user accounts", ["key", "name", "email", "employee_id", "status", "last_signin", "mfa", "department"]),
    "group": ("groups", ["key", "name", "members"]),
    "app": ("app registrations", ["key", "name", "secret_expires", "status"]),
    "contact": ("contacts", ["key", "name", "email", "account", "status"]),
    "deal": ("opportunities", ["key", "name", "account", "amount", "stage", "close_date"]),
    "part": ("parts", ["key", "number", "name", "revision", "state", "type", "modified"]),
    "change": ("change notices", ["key", "name", "state", "due", "owner", "overdue_days"]),
    "site": ("sites and libraries", ["key", "name", "url", "items"]),
    "item": ("files and folders", ["key", "name", "site", "kind", "size", "modified", "sharing"]),
    "pipeline": ("pipelines", ["key", "name", "repository", "last_status", "last_run"]),
    "deployment": ("deployments", ["key", "name", "environment", "status", "when", "error"]),
    "integration": ("integrations", ["key", "name", "platform", "area", "status", "version", "schema_version", "clear_secret"]),
    "api": ("APIs", ["key", "name", "version", "type", "status"]),
    "application": ("apps", ["key", "name", "platform", "owner", "version", "status", "modified"]),
    "release": ("releases", ["key", "name", "app", "version", "track", "rollout", "status", "when", "error"]),
}
LEGAL = re.compile(r"\b(ltd|limited|pvt|private|plc|llp|llc|inc|co|company|corp|corporation|gmbh|ag|sa|bv)\b\.?", re.I)
GSTIN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ISO3 = {"GBR": "GB", "IND": "IN", "USA": "US", "DEU": "DE", "FRA": "FR", "IRL": "IE", "ARE": "AE", "SGP": "SG", "AUS": "AU", "NLD": "NL"}
COUNTRY_NAMES = {"united kingdom": "GB", "uk": "GB", "great britain": "GB", "india": "IN", "united states": "US", "usa": "US", "germany": "DE", "france": "FR", "ireland": "IE"}


def label(entity: str) -> str:
    return ENTITY.get(entity, (entity + "s", []))[0]


def norm_name(s) -> str:
    """A name as a duplicate check sees it: lower case, no legal suffix (Ltd, Pvt, Inc …), no punctuation."""
    s = LEGAL.sub(" ", str(s or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def iso2(v) -> str:
    s = str(v or "").strip()
    if len(s) == 3 and s.upper() in ISO3:
        return ISO3[s.upper()]
    return COUNTRY_NAMES.get(s.lower(), s.upper()[:2] if len(s) == 2 else s)


def num(v):
    if v in (None, ""):
        return None
    try:
        f = float(str(v).replace(",", ""))
        return int(f) if f.is_integer() else round(f, 2)
    except ValueError:
        return None


def day(v) -> str:
    """Any vendor date (ISO, /Date(ms)/, 'YYYY-MM-DD HH:MM:SS', M/D/YYYY) as YYYY-MM-DD."""
    s = str(v or "").strip()
    if re.fullmatch(r"\d{8}", s):                       # SAP's YYYYMMDD
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    m = re.match(r"/Date\((-?\d+)", s)
    if m:
        return datetime.fromtimestamp(int(m.group(1)) / 1000, timezone.utc).strftime("%Y-%m-%d")
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return s[:10]


def when(v) -> float | None:
    """Any vendor timestamp as epoch seconds (None when it cannot be read)."""
    s = str(v or "").strip()
    if not s:
        return None
    if re.fullmatch(r"-?\d+(\.\d+)?", s) and float(s) > 10 ** 8:     # already epoch seconds (a snapshot)
        return float(s)
    if re.fullmatch(r"\d{8}", s):
        s = f"{s[:4]}-{s[4:6]}-{s[6:]}"
    m = re.match(r"/Date\((-?\d+)", s)
    if m:
        return int(m.group(1)) / 1000
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T") if "T" in s or " " in s else s + "T00:00:00+00:00").replace(tzinfo=None).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def stamp(t: float | None) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%d %b %Y %H:%M") if t else "—"


def slug(s) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:40] or "x"


def flat(row: dict) -> dict:
    """A vendor record as one row of scalars (nested values as JSON) — what read() shows in the tool's own terms."""
    out = {}
    for k, v in row.items():
        if k.startswith(("__", "@", "_")) or k == "links":
            continue
        out[k] = json.dumps(v, default=str)[:300] if isinstance(v, (dict, list)) else v
    return out


# ================================================================== the adapter base

class SysAdapter(sdk.Adapter):
    """A business system behind the Connector SDK. A platform implements sign_in, fetch(entity), canon(entity, row),
    runs() and the write ops it supports; reads, the object list, the test and the guarded write come from here."""
    category = "erp"
    can_write = True
    signin = ["password"]
    simulator = ""                       # the mock-lab simulator that stands in for it (tests/mocklab/sims)
    docs = ""
    ENTITIES: dict = {}                  # canonical entity -> (the platform's own object name, what it holds)
    WRITABLE: dict = {}                  # canonical entity -> fields an update may change
    CREATES: tuple = ()                  # canonical entities this platform can create
    JOBS = "Scheduled jobs"              # what the platform calls its scheduled work
    DEACTIVATE: dict = {}                # canonical entity -> {field: value} that blocks / deactivates a record

    # ---- how the platform is reached (override what differs)
    def base(self, c: dict) -> str:
        return (c.get("config") or {}).get("base_url") or ""

    def sign_in(self, api: Api) -> dict:  # noqa: ARG002
        return {}

    def expired(self, r: httpx.Response) -> bool:
        return r.status_code == 401

    def on_expired(self, api: Api) -> None:
        api.state.clear()

    def throttled(self, r: httpx.Response) -> bool:  # noqa: ARG002
        return False

    def retry_after(self, r: httpx.Response) -> float | None:
        v = r.headers.get("Retry-After")
        try:
            return float(v) if v else None
        except ValueError:
            return None

    def error_text(self, r: httpx.Response) -> str:
        try:
            b = r.json()
        except ValueError:
            return re.sub(r"<[^>]+>", " ", r.text or "").strip()[:240] or f"HTTP {r.status_code}"
        for path in (("error", "message", "value"), ("error", "innererror", "message"), ("error", "message"), ("o:errorDetails", 0, "detail"), ("errorSummary",),
                     ("message",), ("Message",), ("detail",), ("error_description",), ("error",), ("fault", "faultstring"), ("Fault", "Error", 0, "Detail")):
            cur = b
            try:
                for p in path:
                    cur = cur[p]
            except (KeyError, IndexError, TypeError):
                continue
            if isinstance(cur, str) and cur.strip():
                return cur.strip()[:300]
        return json.dumps(b)[:240]

    def check(self, r: httpx.Response, what: str, ok: tuple = (200, 201, 202, 204)):
        if r.status_code == 401 or self.expired(r):
            raise connectors.Reconsent(f"{self.label} refused the sign-in ({r.status_code}): {self.error_text(r)}")
        if r.status_code not in ok:
            raise connectors.ConnectorError(f"{self.label} · {what}: {r.status_code} {self.error_text(r)}")
        if not r.content:
            return {}
        try:
            return r.json()
        except ValueError:
            return {"_text": r.text}

    # ---- what a platform implements
    def fetch(self, api: Api, entity: str) -> list[dict]:
        raise connectors.ConnectorError(f"{self.label} does not hold {label(entity)}")

    def canon(self, entity: str, row: dict) -> dict:  # noqa: ARG002
        return row

    def runs(self, api: Api) -> list[dict]:  # noqa: ARG002
        """Job / script / integration runs, newest first: {"job", "label", "id", "started", "ended", "status": succeeded|failed|warning|running|queued, "error"}."""
        return []

    def job_log(self, api: Api, run: dict) -> list[str]:  # noqa: ARG002
        return [run["error"]] if run.get("error") else []

    def payload(self, entity: str, rec: dict) -> dict:
        """A canonical record as the platform's create body (what the approval shows and the write sends)."""
        return {k: v for k, v in rec.items() if v not in (None, "") and k != "ref"}

    def problems(self, c: dict, entity: str, rec: dict) -> list[str]:  # noqa: ARG002
        """What this platform would refuse in a create (the dry run lists it; nothing is sent)."""
        return []

    def field_problems(self, entity: str, field: str, value) -> list[str]:  # noqa: ARG002
        """What this platform would refuse in one field of an update (a Change's dry run lists it)."""
        return []

    def prepare(self, c: dict, entity: str, rec: dict) -> dict:  # noqa: ARG002
        """A canonical record in this platform's own terms before it is loaded (its settings applied: a grouping, a
        legal entity). What changes here is listed as converted by rule, not compared as if it were carried over."""
        return rec

    def op_create(self, api: Api, entity: str, rec: dict, approval: str) -> dict:
        raise connectors.ConnectorError(f"{self.label} does not create {label(entity)} through Relay")

    def op_update(self, api: Api, entity: str, key: str, changes: dict, approval: str) -> dict:
        raise connectors.ConnectorError(f"{self.label} does not update {label(entity)} through Relay")

    def op_rerun(self, api: Api, job: str, run_id: str, approval: str) -> dict:
        raise connectors.ConnectorError(f"{self.label} does not run {self.JOBS.lower()} through Relay")

    def op_status(self, api: Api, ref: dict) -> dict:
        """The state of something a write started (a rerun): {"status", "error"}."""
        return {"status": "unknown"}

    # ---- the SDK contract, from the above
    def session(self, c: dict) -> Api:
        return Api(self, c)

    def records(self, api: Api, entity: str) -> list[dict]:
        out = []
        for row in self.fetch(api, entity):
            r = self.canon(entity, row)
            if r is not None:
                out.append({f: r.get(f) for f in ENTITY.get(entity, ("", list(r)))[1]} | {k: v for k, v in r.items() if k not in ENTITY.get(entity, ("", []))[1]})
        return out

    def test(self, c: dict) -> dict:
        api = self.session(c)
        try:
            ent = next(iter(self.ENTITIES))
            n = len(self.fetch(api, ent))
            return {"ok": True, "sees": f"{n} {label(ent)} ({self.ENTITIES[ent][0]})"}
        finally:
            api.close()

    def list_objects(self, c: dict, search: str = "") -> list[dict]:
        objs = [{"object": obj, "type": what} for obj, what in self.ENTITIES.values()] + ([{"object": "jobs", "type": self.JOBS}] if type(self).runs is not SysAdapter.runs else [])
        return [o for o in objs if search.lower() in (o["object"] + " " + o["type"]).lower()]

    def entity_of(self, obj: str) -> str | None:
        return next((e for e, (o, _) in self.ENTITIES.items() if o.lower() == str(obj).lower() or e == str(obj).lower()), None)

    def read(self, c: dict, obj: str, limit: int = 100) -> dict:
        api = self.session(c)
        try:
            if obj == "jobs":
                rows = self.runs(api)
            else:
                ent = self.entity_of(obj)
                if not ent:
                    raise connectors.ConnectorError(f"{self.label} has no object {obj} in Relay")
                rows = self.fetch(api, ent)
            out = [flat(r) for r in rows]
            cols = []
            for r in out[:200]:
                cols += [k for k in r if k not in cols]
            return {"columns": cols, "rows": out[:limit], "row_count": len(out)}
        finally:
            api.close()

    def rows(self, c: dict, obj: str, max_rows: int):
        """An extract for a dashboard (adapters with `extract = True`): every record of one object in the vendor's own
        fields, nested values as whole JSON text, in pages of 50,000."""
        if not self.extract:
            return super().rows(c, obj, max_rows)
        ent = self.entity_of(obj)
        if not ent:
            raise connectors.ConnectorError(f"{self.label} has no object {obj} in Relay")
        api = self.session(c)
        try:
            recs = self.fetch(api, ent)[:max_rows]
        finally:
            api.close()
        out = [{k: json.dumps(v, default=str) if isinstance(v, (dict, list)) else v for k, v in r.items() if not k.startswith(("__", "@", "_")) and k != "links"} for r in recs]
        return [out[i:i + 50_000] for i in range(0, len(out), 50_000)]

    def _write(self, c: dict, obj: str, payload: dict, approval: str) -> dict:
        """Every op of the approved change, each call carrying X-Relay-Approval; per-op results (all failed: an error)."""
        if "ops" not in (payload or {}):                  # a Workflows write (a test run, a deploy) on this shared connection
            other = next((sdk.get(k) for k, v in ALIAS.items() if v == self.kind), None)
            if other is not None and other is not self:
                return other._write(c, obj, payload, approval)
        api = self.session(c)
        results = []
        try:
            for op in payload.get("ops") or []:
                try:
                    if op["op"] == "create":
                        res = self.op_create(api, op["entity"], op["data"], approval)
                    elif op["op"] in ("update", "deactivate"):
                        res = self.op_update(api, op["entity"], op["key"], op["data"], approval)
                    elif op["op"] == "rerun":
                        res = self.op_rerun(api, op["job"], op.get("run") or "", approval)
                    else:
                        raise connectors.ConnectorError(f"unknown change {op['op']}")
                    results.append({"op": op["op"], "ref": op.get("ref") or op.get("key") or op.get("job"), "ok": True, **(res or {})})
                except (connectors.ConnectorError, sdk.ScopeError) as e:
                    results.append({"op": op["op"], "ref": op.get("ref") or op.get("key") or op.get("job"), "ok": False, "error": str(e)[:400]})
        finally:
            api.close()
        good = sum(1 for r in results if r["ok"])
        if results and not good:
            raise connectors.ConnectorError("; ".join(r["error"] for r in results[:3]))
        return {"ok": True, "written": good, "failed": len(results) - good, "results": results, "approval": approval}


def register(adapter: SysAdapter) -> SysAdapter:
    """The adapter joins the Connector SDK and the Connections hub's catalogue (connectors.KINDS) — no shared edit."""
    sdk.register(adapter)
    d = adapter.describe()
    connectors.KINDS[adapter.kind] = {"label": d["label"], "dialect": None, "auth": list(d["auth"]), "fields": [(f["key"], f["label"], f["required"]) for f in d["fields"]],
                                      "secrets": d["secrets"], "category": d["category"], "sdk": True}
    return adapter


ALIAS = {"boomi_atomsphere": "boomi", "mulesoft_anypoint": "mulesoft"}     # Workflows' connections to the same platforms (see _w2.ALIAS)


def adapter_of(c: dict) -> SysAdapter | None:
    a = sdk.get(c["kind"])
    if not isinstance(a, SysAdapter) and c["kind"] in ALIAS:
        a = sdk.get(ALIAS[c["kind"]])
    return a if isinstance(a, SysAdapter) else None


class SysPlatform(wb.Platform):
    """A platform family of a Systems pack: the connection kinds it reads and the exports a person may upload."""

    def __init__(self, label_: str, kinds: tuple, simulator: str, reads: str, uploads: tuple = ()):
        self.label, self.kinds, self.simulator, self.reads, self.uploads = label_, kinds, simulator, reads, uploads

    def logs(self, ctx, since=None):
        out = []
        for c, a in systems(ctx, self.kinds):
            api = a.session(c)
            try:
                for r in a.runs(api):
                    if since is None or (r.get("started") or 0) >= since:
                        out.append({"when": r.get("started"), "what": r.get("label") or r["job"], "status": r["status"], "detail": r.get("error") or ""})
            finally:
                api.close()
        return out


# ================================================================== a step's view of its systems (sessions per step, closed at the end)

class Seen:
    """What one step reads: a session per connection and canonical rows per (connection, entity), read once."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.apis: dict[str, Api] = {}
        self.rows: dict[tuple, list] = {}
        self.run_cache: dict[str, list] = {}

    def api(self, c: dict, a: SysAdapter) -> Api:
        if c["id"] not in self.apis:
            self.apis[c["id"]] = a.session(c)
        return self.apis[c["id"]]

    def records(self, c: dict, a: SysAdapter, entity: str) -> list[dict]:
        k = (c["id"], entity)
        if k not in self.rows:
            try:
                self.rows[k] = a.records(self.api(c, a), entity)
            except connectors.ConnectorError as e:
                raise wb.StepFailed(f"{c['name']} could not be read: {e}") from e
        return self.rows[k]

    def runs(self, c: dict, a: SysAdapter) -> list[dict]:
        if c["id"] not in self.run_cache:
            try:
                self.run_cache[c["id"]] = a.runs(self.api(c, a))
            except connectors.ConnectorError as e:
                raise wb.StepFailed(f"{c['name']} could not be read: {e}") from e
        return self.run_cache[c["id"]]

    def close(self) -> None:
        for a in self.apis.values():
            a.close()


def stepfn(fn: Callable) -> Callable:
    """A step that reads systems: one Seen per run, its sessions closed when the step ends."""
    def run(ctx, *a):
        seen = Seen(ctx)
        ctx.seen = seen
        try:
            return fn(ctx, *a)
        except connectors.Reconsent as e:
            raise wb.StepFailed(f"Sign in again: {e}") from e
        except connectors.ConnectorError as e:
            raise wb.StepFailed(str(e)) from e
        finally:
            seen.close()
    run.__name__ = getattr(fn, "__name__", "step")
    return run


def systems(ctx, kinds: tuple | None = None) -> list[tuple[dict, SysAdapter]]:
    """The item's connections that a Systems adapter reaches (optionally only these kinds), as its owner may use them."""
    out = []
    for c in ctx.connections():
        a = adapter_of(c)
        if a and (not kinds or c["kind"] in kinds):
            out.append((c, a))
    return out


# ================================================================== files in the item's folder (snapshots the proofs read)

def snap(ctx, name: str, rows: list[dict], cols: list[str] | None = None) -> str:
    """Rows to data/<name>.csv (LF, plain values) — the proofs read them with DuckDB; returns the file name."""
    name = re.sub(r"[^\w.\-]+", "_", name)[:80] + ".csv"
    cols = cols or []
    for r in rows:
        cols += [k for k in r if k not in cols]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols or ["key"])
    for r in rows:
        w.writerow(["" if r.get(k) is None else ("true" if r.get(k) is True else "false" if r.get(k) is False else json.dumps(r[k], default=str) if isinstance(r.get(k), (dict, list)) else r.get(k))
                    for k in cols])
    d = ctx.dir / "data"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(buf.getvalue(), encoding="utf-8", newline="")
    return name


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def upload_rows(ctx, f: dict) -> tuple[list[str], list[dict]]:
    """An uploaded export as rows: CSV / an Excel workbook's first sheet / tab-delimited text (SAP table downloads) / JSON."""
    p = ctx.dir / "data" / (f.get("table") or f["name"])
    if not p.exists():
        raise wb.StepFailed(f"{f['name']} is not in the work item's data folder any more.")
    text = p.read_text(encoding="utf-8-sig", errors="replace")
    if p.suffix.lower() == ".json":
        try:
            body = json.loads(text)
        except ValueError as e:
            raise wb.StepFailed(f"{f['name']} is not JSON: {e}") from e
        rows = body if isinstance(body, list) else next((v for v in body.values() if isinstance(v, list)), []) if isinstance(body, dict) else []
        rows = [flat(r) for r in rows if isinstance(r, dict)]
        cols = []
        for r in rows:
            cols += [k for k in r if k not in cols]
        return cols, rows
    first = text.split("\n", 1)[0]
    delim = "\t" if first.count("\t") > first.count(",") else ";" if first.count(";") > first.count(",") else ","
    rd = csv.DictReader(io.StringIO(text), delimiter=delim)
    rows = [{(k or "").strip(): (v or "").strip() for k, v in r.items() if k is not None} for r in rd]
    return [c.strip() for c in (rd.fieldnames or [])], rows


# ================================================================== mapping a source's columns onto canonical fields (rules first)

SYNONYMS = {
    "key": ["key", "id", "code", "number", "no", "account", "account_number", "customer_id", "customer_code", "customer_number", "customeraccount", "vbeln", "kunnr", "lifnr", "matnr",
            "supplier_id", "supplier_code", "vendor_id", "vendoraccountnumber", "employee_id", "employee_no", "employeenumber", "worker_id", "user_id", "login", "upn", "sku", "part_number",
            "partnumber", "item_id", "entityid", "businesspartner", "ledger_code", "account_code", "guid"],
    "number": ["number", "customer_number", "customer_code", "account_number", "code", "entityid", "ref", "reference", "employee_number", "employee_no", "employeenumber", "personnel_number", "part_number", "partnumber", "item_id", "itemid"],
    "name": ["name", "name1", "company", "company_name", "companyname", "organisation", "organization", "organizationname", "organisationname", "customer_name", "supplier_name",
             "vendor_name", "vendororganizationname", "account_name", "full_name", "fullname", "displayname", "display_name", "businesspartnerfullname", "description", "ledger", "ledger_name",
             "product_name", "item_name", "title", "maktx", "folder", "folder_name", "file_name", "filename", "document_name"],
    "email": ["email", "e-mail", "mail", "email_address", "emailaddress", "primarycontactemail", "smtp_addr", "work_email"],
    "country": ["country", "country_code", "countrycode", "land1", "addresscountryregionid", "country_region", "usagelocation", "taxpayercountry"],
    "city": ["city", "town", "ort01", "addresscity", "cityname"],
    "currency": ["currency", "currency_code", "currencycode", "waers", "waerk", "salescurrencycode", "curr"],
    "tax_id": ["tax_id", "taxid", "gstin", "gst", "gst_number", "vat", "vat_number", "tax_number", "taxnumber", "stcd3", "bptaxnumber", "taxexemptnumber", "defaulttaxreg", "tax_registration"],
    "credit_limit": ["credit_limit", "creditlimit", "credit", "klimk"],
    "status": ["status", "state", "active", "blocked", "isinactive", "onholdstatus", "sperr", "lvorm", "loevm", "account_status"],
    "created": ["created", "created_at", "creationdate", "datecreated", "erdat", "ersda", "create_date"],
    "terms": ["terms", "payment_terms", "paymentterms", "paymenttermsname", "zterm", "payment_terms_days"],
    "sku": ["sku", "product", "material", "matnr", "itemnumber", "item_number", "default_code", "product_code"],
    "category": ["category", "product_group", "productgroup", "matkl", "group"],
    "uom": ["uom", "unit", "base_unit", "baseunit", "meins", "unit_of_measure"],
    "price": ["price", "unit_price", "sales_price", "salesprice", "list_price"],
    "department": ["department", "dept", "org_unit", "cost_centre"],
    "employee_id": ["employee_id", "employeeid", "employee_number", "employeenumber", "personnel_number"],
    "date": ["date", "order_date", "invoice_date", "trandate", "posting_date", "audat"],
    "amount": ["amount", "total", "total_amount", "totalnetamount", "gross_amount", "invoiceamount", "netwr"],
    "customer": ["customer", "sold_to", "soldtoparty", "customer_id", "kunnr", "partner"],
    "group": ["group", "customer_group", "customergroupid", "ktokd", "account_group", "parent", "under", "type"],
    "debit": ["debit", "dr", "debit_amount", "opening_debit"],
    "revision": ["revision", "rev", "version", "item_revision_id", "revision_id"],
    "state": ["state", "lifecycle_state", "lifecycle", "release_status", "release_state", "maturity"],
    "stage": ["stage", "stagename", "stage_name", "deal_stage", "dealstage", "sales_stage", "pipeline_stage"],
    "close_date": ["close_date", "closedate", "expected_close_date", "expected_close", "closing_date", "close"],
    "credit": ["credit", "cr", "credit_amount", "opening_credit"],
}


def _ck(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


def suggest_mapping(cols: list[str], fields: list[str], rows: list[dict] | None = None) -> dict[str, tuple[str, str]]:
    """{canonical field: (source column, why)}: the column's own name, then a known synonym, then what the values look like."""
    out: dict[str, tuple[str, str]] = {}
    used: set[str] = set()
    for f in fields:
        hit = next((c for c in cols if _ck(c) == f and c not in used), None)
        why = "same name"
        if not hit:
            syn = [_ck(s) for s in SYNONYMS.get(f, [])]
            hit = next((c for s in syn for c in cols if _ck(c) == s and c not in used), None)
            why = "a known name for it"
        if not hit and rows:
            vals = {c: [str(r.get(c) or "") for r in rows[:50] if r.get(c)] for c in cols if c not in used}
            if f == "email":
                hit = next((c for c, vs in vals.items() if vs and all(EMAIL.match(v) for v in vs)), None)
            elif f == "tax_id":
                hit = next((c for c, vs in vals.items() if vs and all(GSTIN.match(v) for v in vs)), None)
            why = "what its values look like"
        if hit:
            out[f] = (hit, why)
            used.add(hit)
    if "number" in fields and "number" not in out and "key" in out:      # a part / employee number is the record's key AND its visible number
        if _ck(out["key"][0]) in {_ck(s) for s in SYNONYMS.get("number", [])}:
            out["number"] = (out["key"][0], "the same column as the key")
    return out


TRANSFORMS = (("", "As is"), ("trim", "Trim spaces"), ("upper", "Upper case"), ("lower", "Lower case"), ("iso2", "Country to ISO 2 (GBR, India → GB, IN)"),
              ("number", "Number"), ("date", "Date (YYYY-MM-DD)"), ("active", "Active / blocked from a flag"))


def apply(rule: str, v):
    if v is None:
        return None
    s = str(v).strip()
    if rule == "upper":
        return s.upper()
    if rule == "lower":
        return s.lower()
    if rule == "iso2":
        return iso2(s)
    if rule == "number":
        return num(s)
    if rule == "date":
        return day(s)
    if rule == "active":
        return "blocked" if s.lower() in ("x", "true", "1", "yes", "blocked", "inactive", "all", "t") else "active"
    return s


def map_rows(rows: list[dict], mapping: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        rec = {}
        for m in mapping:
            v = m.get("constant") if m.get("constant") not in (None, "") else (r.get(m["source"]) if m.get("source") else None)
            rec[m["id"]] = apply(m.get("rule") or "", v) if v not in (None, "") else None
        out.append(rec)
    return out


# ================================================================== value rules every record passes before anything is written

def value_problems(entity: str, rec: dict) -> list[str]:
    out = []
    if entity in ("customer", "supplier", "product", "part", "contact", "account", "worker", "user") and not rec.get("name"):
        out.append("no name")
    if rec.get("email") and not EMAIL.match(str(rec["email"])):
        out.append(f"e-mail {rec['email']!r} is not an address")
    if rec.get("country") and not re.fullmatch(r"[A-Z]{2}", str(rec["country"])):
        out.append(f"country {rec['country']!r} is not an ISO 2 code")
    if rec.get("currency") and not re.fullmatch(r"[A-Z]{3}", str(rec["currency"])):
        out.append(f"currency {rec['currency']!r} is not an ISO 3 code")
    if entity in ("customer", "supplier") and rec.get("country") == "IN" and rec.get("tax_id") and not GSTIN.match(str(rec["tax_id"])):
        out.append(f"GSTIN {rec['tax_id']} does not have the GSTIN format")
    if rec.get("credit_limit") not in (None, "") and num(rec.get("credit_limit")) is None:
        out.append(f"credit limit {rec['credit_limit']!r} is not a number")
    return out


def dupes(rows: list[dict], fieldname: str = "name") -> list[list[dict]]:
    """Clusters of records whose names are the same once legal suffixes and punctuation are gone (Hilltop Grocers ↔ Hilltop Grocers Ltd)."""
    by: dict[str, list] = {}
    for r in rows:
        n = norm_name(r.get(fieldname))
        if n:
            by.setdefault(n, []).append(r)
    return [v for v in by.values() if len(v) > 1]


# ================================================================== writes: a per-change approval, X-Relay-Approval, and the hook back

def request_write(ctx, c: dict, obj: str, ops: list[dict], what: str, items: list[str]) -> dict:
    """The approved-write path of the workbench (ctx.request_write: connectors.request_write + a hand-off on the item),
    with the change in plain words for the approver and a link back to the item. Nothing is written before a named
    person accepts it; the adapter then sends each call with X-Relay-Approval: <checkpoint id>."""
    payload = {"from": f"{ctx.module}:{ctx.id}:{ctx.step_id}", "ops": ops}
    try:
        cp = connectors.request_write(c, obj, payload, ctx.who or ctx.owner, module=ctx.module_name, what=f"{what} ({_secrets.token_hex(2)})"[:200], items=items[:12],
                                      link=wb.route_of(ctx.st) + f"?step={ctx.step_id}")
    except (sdk.ScopeError, connectors.ConnectorError) as e:
        raise wb.StepFailed(str(e)) from e
    ctx._handoff({"kind": "write", "label": what, "connection": c["name"], "checkpoint": cp["id"], "status": "awaiting approval", "link": "#/validate", "ops": len(ops)})
    return cp


def pending(cp: dict, c: dict, n: int) -> dict:
    """The gate row of a write that waits for its approval (replaced by the read-back once it is written)."""
    return {"name": f"write:{cp['id']}", "label": f"Write to {c['name']}: {n} change(s)", "status": "skip", "measured": "awaiting approval", "expected": "approved, then read back",
            "detail": f"Waiting in the Validation queue ({cp['id']}) — nothing is written until a named person accepts it."}


def writes(ctx, step: str | None = None) -> list[dict]:
    """The write hand-offs of this item (optionally of one step), with what the approval and the system said."""
    return [h for h in (ctx.data.get("_handoffs") or []) if h.get("kind") == "write" and (step is None or h.get("step") == step)]


def _on_write(cp: dict, event: str, result) -> None:
    """connectors' write hook: the approved change was written (or failed, or was sent back). The item records the
    outcome on its hand-off and, when the step has a `verify` action, Relay reads the system back and reconciles."""
    origin = str(((cp.get("evidence") or {}).get("payload") or {}).get("from") or "")
    parts = origin.split(":")
    if len(parts) < 3:
        return
    pid, sid = parts[1], parts[2]
    status = {"written": "written", "failed": "failed", "sent_back": "sent back"}.get(event, event)

    def f(st):
        for h in (st.get("data") or {}).get("_handoffs") or []:
            if h.get("checkpoint") == cp["id"]:
                h["status"] = status
                h["decided"] = time.time()
                if isinstance(result, dict):
                    h["result"] = {k: result.get(k) for k in ("written", "failed", "results")}
                    if h["result"].get("results"):
                        h["result"]["results"] = h["result"]["results"][:200]
                else:
                    h["detail"] = str(result or "")[:400]
    try:
        wb._mutate(pid, f)
        st = wb._load(pid)
    except (KeyError, FileNotFoundError):
        return
    wb.store.log(pid, {"kind": "app", "stage": f"{st['module']}.{sid}", "level": "ok" if event == "written" else "warn",
                       "text": f"The approved change was {status}" + (f": {result.get('written')} written, {result.get('failed')} failed." if isinstance(result, dict) else f": {str(result or '')[:200]}")})
    spec = wb.PACKS.get(st["module"]).step(st["work"], sid) if wb.PACKS.get(st["module"]) else None
    if event == "written" and spec and "verify" in spec.actions and not st.get("closed"):
        try:
            wb.start(pid, sid, who=None, action="verify", _internal=True)
        except Exception:  # noqa: BLE001 - a person can still start "Read back and reconcile" on the step
            pass


def hook(module: str) -> None:
    connectors.register_write_hook(module, _on_write)


# ================================================================== learned fixes (Change › Learn): the next diagnosis is faster

def learned(module: str) -> list[dict]:
    return [{**r, "ops": json.loads(r["ops"] or "[]")} for r in db.q("SELECT * FROM w3_rules WHERE module = ? ORDER BY updated DESC", (module,))]


def learn(module: str, signature: str, cause: str, fix: str, ops: list, item: str, who: str | None) -> str:
    have = db.one("SELECT id FROM w3_rules WHERE module = ? AND signature = ?", (module, signature))
    now = time.time()
    if have:
        db.run("UPDATE w3_rules SET cause = ?, fix = ?, ops = ?, learned_from = ?, learned_by = ?, updated = ? WHERE id = ?", (cause, fix, json.dumps(ops), item, who, now, have["id"]))
        return have["id"]
    rid = "w3r-" + _secrets.token_hex(4)
    db.run("INSERT INTO w3_rules (id, module, signature, cause, fix, ops, learned_from, learned_by, uses, created, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
           (rid, module, signature, cause, fix, json.dumps(ops), item, who, now, now))
    db.audit("w3.rule.learned", rid, {"module": module, "signature": signature[:120], "item": item}, who or "agent")
    return rid


# ================================================================== a Systems module, for the generic journeys

@dataclass
class Signature:
    """A vendor error Relay recognises: its likely cause, the fix in plain words, and (optionally) the changes it
    proposes — fn(ctx, c, a, api, run) -> [change rows] — so Change can prepare them for a person."""
    pattern: str
    cause: str
    fix: str
    propose: Callable | None = None
    route: str = "change"                   # Run's default route for it: change | heal | ticket
    kinds: tuple = ()                       # connection kinds it belongs to: an error pasted into a request is matched there

    def match(self, text: str) -> re.Match | None:
        return re.search(self.pattern, text or "", re.I)


@dataclass
class Spec:
    module: str
    noun: str                                # "ERP", "CRM" … (in sentences)
    system: str                              # the lineage system of the module's own nodes ("Relay ERP")
    entities: tuple                          # canonical entities it reads, most important first
    rules: list = field(default_factory=list)          # health rules: fn(ctx, inv) -> [finding]
    signatures: list = field(default_factory=list)     # Signature list (job errors Relay recognises)
    minutes: dict = field(default_factory=dict)        # estimate: minutes per finding kind, "per_100" per 100 records moved
    monitors: list = field(default_factory=list)       # Run › Watch extras: fn(ctx, inv) -> [gate row with "break" details]
    upload_entities: dict = field(default_factory=dict)   # file-name word -> entity (for exports), e.g. {"kna1": "customer"}
    inventory_extra: Callable | None = None  # fn(ctx, seen) -> extra inventory rows (custom code, configuration)
    creates: tuple = ()                      # entities Develop brings into the system (an inbound interface)
    measures: dict = field(default_factory=dict)       # entity -> (measure, by) a migration's control totals use


MINUTES = {"failing_job": 120, "warning_job": 60, "duplicate": 20, "missing_tax": 10, "invalid_tax": 15, "blocked": 2, "per_100": 30, "missing_email": 5}
SEV_ORDER = {"high": 0, "medium": 1, "low": 2}


def finding(kind: str, system: str, entity: str, record: str, what: str, severity: str, *, measured="", fix: str = "", work: str = "change", evidence: str | None = None, **extra) -> dict:
    return {"id": f"{kind}:{slug(system)}:{entity}:{slug(record)}", "kind": kind, "system": system, "entity": entity, "record": record, "what": what, "severity": severity,
            "measured": measured, "fix": fix, "work": work, "decision": "keep", "evidence": evidence, **extra}


class Inv:
    """The inventory a health rule reads: the systems (their canonical rows and job runs) and the uploaded exports."""

    def __init__(self, ctx, items: list[dict]):
        self.ctx = ctx
        self.items = items                  # inventory records (included ones)

    def rows(self, entity: str) -> list[tuple[str, list[dict]]]:
        out = []
        for it in self.items:
            if it.get("entity") == entity and it.get("file") and (self.ctx.dir / "data" / it["file"]).exists():
                out.append((it["system"], read_csv(self.ctx.dir / "data" / it["file"])))
        return out

    def runs(self) -> list[tuple[str, list[dict]]]:
        out = []
        for it in self.items:
            if it.get("entity") == "jobs" and it.get("file") and (self.ctx.dir / "data" / it["file"]).exists():
                out.append((it["system"], read_csv(self.ctx.dir / "data" / it["file"])))
        return out


# ---- built-in health rules (each returns findings; the pack lists the ones that fit)

def rule_failing_jobs(ctx, inv: Inv, spec: "Spec | None" = None) -> list[dict]:
    out = []
    for system, runs in inv.runs():
        by: dict[str, list] = {}
        for r in runs:
            by.setdefault(r["job"], []).append(r)
        for job, rs in by.items():
            rs.sort(key=lambda x: float(x.get("started") or 0), reverse=True)
            streak = []
            for r in rs:
                if r["status"] in ("failed", "warning"):
                    streak.append(r)
                else:
                    break
            if len(streak) >= 2 or (streak and len(rs) == 1):
                err = streak[0].get("error") or ""
                sig = next((s for s in (spec.signatures if spec else []) if s.match(err)), None)
                kind = "failing_job" if streak[0]["status"] == "failed" else "warning_job"
                out.append(finding(kind, system, "jobs", job, f"{streak[0].get('label') or job}: the last {len(streak)} run(s) {'failed' if kind == 'failing_job' else 'ended in a warning'} — {err[:200]}",
                                   "high" if kind == "failing_job" else "medium", measured=f"{len(streak)} of the last {min(len(rs), 14)} runs since {stamp(float(streak[-1].get('started') or 0))}",
                                   fix=(sig.fix if sig else "Read the job log and fix the cause, then run it again."), work="change", cause=(sig.cause if sig else "")))
    return out


def rule_duplicates(entity: str) -> Callable:
    def rule(ctx, inv: Inv, spec=None):
        out = []
        for system, rows in inv.rows(entity):
            for group in dupes(rows):
                names = sorted({str(r.get("name")) for r in group})
                keep = sorted(group, key=lambda r: str(r.get("created") or ""))[0]
                out.append(finding("duplicate", system, entity, " / ".join(names), f"{len(group)} {label(entity)} are the same once “Ltd” and punctuation go: {', '.join(names)}",
                                   "medium", measured=", ".join(str(r.get("key")) for r in group), fix=f"Keep {keep.get('name')} ({keep.get('key')}); block the other and point its documents to it.",
                                   work="change", keys=[str(r.get("key")) for r in group]))
        return out
    rule.__name__ = f"duplicates_{entity}"
    return rule


def rule_tax_ids(entity: str) -> Callable:
    def rule(ctx, inv: Inv, spec=None):
        out = []
        for system, rows in inv.rows(entity):
            for r in rows:
                if iso2(r.get("country")) != "IN":
                    continue
                t = str(r.get("tax_id") or "").strip()
                if not t:
                    out.append(finding("missing_tax", system, entity, f"{r.get('name')} ({r.get('key')})", f"India {label(entity)[:-1]} without a GSTIN: invoices to it cannot carry one (GSTR-1)", "medium",
                                       fix="Add the GSTIN from the customer's registration certificate.", work="change", keys=[str(r.get("key"))]))
                elif not GSTIN.match(t):
                    out.append(finding("invalid_tax", system, entity, f"{r.get('name')} ({r.get('key')})", f"GSTIN {t} does not have the GSTIN format", "high",
                                       fix="Correct the GSTIN (15 characters: state code, PAN, entity, Z, check digit).", work="change", keys=[str(r.get("key"))]))
        return out
    rule.__name__ = f"tax_ids_{entity}"
    return rule


def rule_blocked(entity: str) -> Callable:
    def rule(ctx, inv: Inv, spec=None):
        out = []
        for system, rows in inv.rows(entity):
            bl = [r for r in rows if str(r.get("status") or "").lower() in ("blocked", "inactive", "terminated", "disabled")]
            if bl:
                out.append(finding("blocked", system, entity, f"{len(bl)} {label(entity)}", f"{len(bl)} {label(entity)} are blocked or inactive: retire candidates for a move, or a clean-up",
                                   "low", measured=", ".join(str(r.get("key")) for r in bl[:8]), fix="Leave them behind in a migration (Decide › retire).", work="migrate",
                                   keys=[str(r.get("key")) for r in bl]))
        return out
    rule.__name__ = f"blocked_{entity}"
    return rule


# ================================================================== the five journeys, generic for a records system

def _sys_or_fail(ctx, kinds=None) -> list[tuple[dict, SysAdapter]]:
    s = systems(ctx, kinds)
    if not s and not ctx.files(UPLOADS):
        raise wb.StepFailed("Nothing to read: pick a connection to the system or upload its exports.")
    return s


def guess_entity(spec: Spec, filename: str) -> str | None:
    n = filename.lower()
    for word, ent in spec.upload_entities.items():
        if word in n:
            return ent
    for ent in spec.entities:
        if ent in n or label(ent).split()[-1].rstrip("s") in n:
            return ent
    return None


def from_upload(ctx, spec: Spec, f: dict) -> tuple[str | None, list[dict], dict]:
    """An export as canonical rows (columns mapped by name, synonym or value — rules first)."""
    ent = guess_entity(spec, f["name"])
    if not ent or ent not in ENTITY:
        return None, [], {}
    cols, rows = upload_rows(ctx, f)
    m = suggest_mapping(cols, ENTITY[ent][1], rows)
    flag = _ck(m.get("status", ("", ""))[0]) in ("sperr", "lvorm", "loevm", "blocked", "isinactive", "active", "inactive")
    rules = {"country": "iso2", "status": "active" if flag else "trim", "credit_limit": "number", "created": "date", "close_date": "date", "price": "number", "amount": "number",
             "debit": "number", "credit": "number"}
    mapping = [{"id": k, "source": src, "rule": rules.get(k, "trim")} for k, (src, _) in m.items()]
    recs = map_rows(rows, mapping)
    for r in recs:
        if r.get("key") in (None, ""):
            r["key"] = r.get("number") or r.get("name")
        if r.get("status") in (None, ""):
            r["status"] = "active"
    return ent, recs, {k: v[0] for k, v in m.items()}


def assess_work(spec: Spec, title: str) -> wb.Work:
    def connect(ctx):
        rows = []
        for c, a in _sys_or_fail(ctx):
            try:
                r = connectors.test({**c, "_who": ctx.who or ctx.owner})
                rows.append([c["name"], a.label, "answered", r.get("sees") or "connected", connectors.SCOPES.get(c.get("scope") or "read")])
            except connectors.ConnectorError as e:
                rows.append([c["name"], a.label, "refused", str(e)[:300], ""])
        for f in ctx.files(UPLOADS):
            rows.append([f["name"], "Export (upload)", "answered", f"{wb._size(f['bytes'])} uploaded", "Read-only copy"])
        good = [r for r in rows if r[2] == "answered"]
        if not good:
            raise wb.StepFailed("None of the sources answered: " + "; ".join(f"{r[0]}: {r[3]}" for r in rows)[:600])
        return {"summary": f"{len(good)} of {len(rows)} source(s) answered — read-only, with the connection's own sign-in.", "counts": {"sources": len(rows), "answered": len(good)},
                "data": {"columns": ["Source", "Platform", "Status", "What Relay sees", "Access"], "rows": rows}}

    @stepfn
    def inventory(ctx):
        have = {r["id"]: r for r in ctx.records(ctx.step_id)}
        items = []
        for c, a in systems(ctx):
            for ent in spec.entities:
                if ent not in a.ENTITIES:
                    continue
                rows = ctx.seen.records(c, a, ent)
                f = snap(ctx, f"inv-{slug(c['name'])}-{ent}", rows, ENTITY[ent][1])
                recent = sum(1 for r in rows if (when(r.get("created")) or 0) > wb.lab_now() - 365 * 86400)
                items.append({"id": f"{c['id']}:{ent}", "include": True, "system": c["name"], "platform": a.label, "object": a.ENTITIES[ent][0], "what": label(ent).capitalize(),
                              "records": len(rows), "usage": f"{recent} created in the last year" if recent else "", "file": f, "entity": ent, "conn": c["id"]})
            if type(a).runs is not SysAdapter.runs:
                runs = ctx.seen.runs(c, a)
                f = snap(ctx, f"inv-{slug(c['name'])}-jobs", runs, ["job", "label", "id", "started", "ended", "status", "error"])
                jobs = {r["job"] for r in runs}
                bad = {r["job"] for r in runs if r["status"] in ("failed", "warning")}
                items.append({"id": f"{c['id']}:jobs", "include": True, "system": c["name"], "platform": a.label, "object": a.JOBS, "what": "Scheduled jobs and their runs",
                              "records": len(jobs), "usage": f"{len(runs)} runs, {len(bad)} job(s) with failures", "file": f, "entity": "jobs", "conn": c["id"]})
        for f in ctx.files(UPLOADS):
            g = guess_entity(spec, f["name"])
            if g and g not in ENTITY:
                continue                                      # the pack reads it itself (Spec.inventory_extra)
            ent, recs, mapped = from_upload(ctx, spec, f)
            if not ent:
                items.append({"id": f"file:{f['name']}", "include": False, "system": f["name"], "platform": "Export (upload)", "object": f["name"], "what": "Not recognised (kept as an attachment)",
                              "records": 0, "usage": "", "file": None, "entity": None})
                continue
            fn = snap(ctx, f"inv-{slug(f['name'])}-{ent}", recs, ENTITY[ent][1])
            items.append({"id": f"file:{f['name']}", "include": True, "system": f["name"], "platform": "Export (upload)", "object": f["name"], "what": label(ent).capitalize(),
                          "records": len(recs), "usage": "columns: " + ", ".join(f"{k} ← {v}" for k, v in list(mapped.items())[:6]), "file": fn, "entity": ent})
        if spec.inventory_extra:
            items += spec.inventory_extra(ctx, ctx.seen) or []
        for it in items:
            if it["id"] in have:
                it["include"] = have[it["id"]].get("include", it["include"])
        if not items:
            raise wb.StepFailed("The sources show nothing Relay knows how to read for this module.")
        ctx.put("inventory", items)
        for it in items:
            if it.get("conn"):
                sysn = ctx.lineage_node("system", it["platform"], it["system"], label=f"{it['system']} ({it['platform']})", own=False)
                if it.get("entity") not in (None, "jobs"):
                    en = ctx.lineage_node("entity", it["platform"], f"{it['system']}:{it['object']}", label=f"{it['object']} · {it['system']}", own=False)
                    ctx.lineage_edge(sysn, en, "contains")
        return {"summary": f"{len(items)} object(s) on {len({i['system'] for i in items})} source(s): " + ", ".join(f"{i['records']} {i['what'].lower()}" for i in items[:5]) + ("…" if len(items) > 5 else "") + ".",
                "counts": {"objects": len(items), "records": sum(i["records"] for i in items)}, "records": items,
                "data": {"columns": ["Include", "Source", "Object (its own name)", "What", "Records", "Usage"],
                         "rows": [["yes" if i["include"] else "no", i["system"], i["object"], i["what"], i["records"], i["usage"]] for i in items]}}

    def health(ctx):
        items = [i for i in ctx.records("inventory") if i.get("include")]
        if not items:
            raise wb.StepFailed("Nothing is included: tick at least one object in the inventory.")
        inv = Inv(ctx, items)
        findings, checks = [], []
        for rule in spec.rules:
            got = rule(ctx, inv, spec)
            name = getattr(rule, "__name__", "rule")
            eid = ctx.evidence(f"Health rule: {name.replace('_', ' ')}", {"rule": name, "findings": got}, kind="rule", ok=not any(f["severity"] == "high" for f in got))
            for f in got:
                f["evidence"] = eid
            findings += got
            worst = min((SEV_ORDER[f["severity"]] for f in got), default=None)
            checks.append({"name": name, "label": getattr(rule, "label", None) or _rule_label(name),
                           "status": "pass" if worst is None else "fail" if worst == 0 else "warn", "measured": len(got), "expected": 0,
                           "detail": "; ".join(f["what"] for f in got[:3])[:400] or "nothing found", "evidence": eid})
        refs = [f"{f['system']}" for f in findings]
        checks.append(ctx.proof("references_real", label="Every finding names a source in the inventory", refs=refs, known=[i["system"] for i in items]))
        findings.sort(key=lambda f: (SEV_ORDER[f["severity"]], f["system"], f["kind"]))
        ctx.put("findings", findings)
        high = sum(1 for f in findings if f["severity"] == "high")
        return {"summary": f"{len(findings)} finding(s) from {len(spec.rules)} rule(s) over {sum(i['records'] for i in items)} record(s): {high} high.",
                "counts": {"findings": len(findings), "high": high}, "data": {"checks": checks}}

    def findings_step(ctx):
        have = {r["id"]: r for r in ctx.records(ctx.step_id)}
        recs = [{**f, **({k: have[f["id"]][k] for k in ("decision", "severity") if k in have[f["id"]]} if f["id"] in have else {})} for f in ctx.get("findings") or []]
        high = sum(1 for r in recs if r["severity"] == "high")
        return {"summary": (f"{len(recs)} finding(s), {high} high — keep what matters, ignore what does not." if recs else f"No issues found: every rule passes on these {spec.noun} sources."),
                "counts": {"findings": len(recs), "high": high}, "records": recs, "items": [f"{r['system']}: {r['what']}"[:240] for r in recs[:6]],
                "data": {"columns": ["Source", "What", "Severity", "Measured", "Fix with"], "rows": [[r["system"], r["what"], r["severity"], r["measured"], f"{wb.WORK_NAME.get(r['work'], r['work'])}: {r['fix']}"] for r in recs]}}

    def estimate(ctx):
        b = registry.brand()
        rate, cur = float(b.get("hourly_rate") or 0), b.get("currency") or ""
        mins = {**MINUTES, **spec.minutes}
        kept = [f for f in ctx.records("findings") if f.get("decision") != "ignore"]
        items, total = [], 0.0
        for name, fs in (("Wave 1 — fix what fails today (high)", [f for f in kept if f["severity"] == "high"]), ("Wave 2 — clean the data (medium and low)", [f for f in kept if f["severity"] != "high"])):
            if not fs:
                continue
            h = sum(mins.get(f["kind"], 30) * (max(1, len(f.get("keys") or [])) if f["kind"] == "blocked" else 1) for f in fs) / 60
            total += h
            items.append({"title": name, "detail": "; ".join(f"{f['system']}: {f['kind'].replace('_', ' ')}" for f in fs[:6]) + (f" and {len(fs) - 6} more" if len(fs) > 6 else ""),
                          "effort": f"{h:.1f} h" + (f" · {cur}{rate * h:,.0f}" if rate else "")})
        moved = sum(i["records"] for i in ctx.records("inventory") if i.get("include") and i.get("entity") not in (None, "jobs"))
        if moved:
            h = moved / 100 * mins["per_100"] / 60
            total += h
            items.append({"title": "If you move it — the records in scope", "detail": f"{moved} record(s): mapping agreed, record-by-record reconciliation, cut-over", "effort": f"{h:.1f} h" + (f" · {cur}{rate * h:,.0f}" if rate else "")})
        assumptions = "; ".join(f"{v} min per {k.replace('_', ' ')}" for k, v in mins.items())
        ctx.output("assessment.md", f"# Assessment: {ctx.title}\n\n" + "\n".join(f"## {i['title']}\n\n{i['detail']}\n\nEffort: {i['effort']}\n" for i in items)
                   + f"\nAssumptions: {assumptions}.\n" + ("" if rate else "No hourly rate is set (Admin › Branding), so no cost is shown.\n"), label="Assessment (Markdown)")
        ctx.output("findings.csv", _csv([{k: f.get(k) for k in ("system", "entity", "record", "what", "severity", "measured", "fix", "decision")} for f in ctx.records("findings")]), label="Findings (CSV)")
        ctx.output("inventory.csv", _csv([{k: i.get(k) for k in ("system", "platform", "object", "what", "records", "usage", "include")} for i in ctx.records("inventory")]), label="Inventory (CSV)")
        return {"summary": f"{len(items)} wave(s), about {total:.1f} h" + (f" ({cur}{rate * total:,.0f} at the hourly rate)" if rate else "") + ".", "counts": {"waves": len(items), "hours": round(total, 1)},
                "data": {"items": items, "total": f"{total:.1f} h", "note": f"Assumptions: {assumptions}." + ("" if rate else " Set an hourly rate under Admin › Branding to see the cost.")}}

    return wb.Work(title=title, steps={
        "Connect": wb.Step(kind="platform", run=connect, agent="Connector", text=f"Each connection is tested with its own sign-in and each export opened — read-only"),
        "Inventory": wb.Step(kind="platform", run=inventory, agent="Scanner", text=f"Every object the {spec.noun} holds, in its own terms, with record counts, usage and its scheduled jobs — you untick what is out of scope",
                             edit=wb.Edit(columns=[wb.Column("include", "Include", "bool"), wb.Column("system", "Source", readonly=True), wb.Column("object", "Object", readonly=True),
                                                   wb.Column("records", "Records", "number", readonly=True)], add=False, remove=False, label="object")),
        "Health": wb.Step(kind="proof", run=health, view="gates", agent="Health checker", text="Rules over every record and run — failing jobs, duplicates, missing or malformed tax ids, blocked masters — each with its evidence"),
        "Findings": wb.Step(kind="person", run=findings_step, edit=wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("keep", "Keep"), ("ignore", "Ignore"))),
                                                                                  wb.Column("severity", "Severity", "select", options=("high", "medium", "low")), wb.Column("system", "Source", readonly=True),
                                                                                  wb.Column("what", "What", readonly=True)], add=False, remove=False, label="finding"),
                            text="What fails today and what to clean, each with the fix and the work type that does it — you keep or ignore each"),
        "Estimate": wb.Step(kind="deterministic", run=estimate, view="plan", agent="Estimator", text="Waves by risk, with a person's time per fix and per hundred records moved — and the cost at your hourly rate"),
    })


def _csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    cols = []
    for r in rows:
        cols += [k for k in r if k not in cols]
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols or ["empty"])
    for r in rows:
        w.writerow(["" if r.get(k) is None else r.get(k) for k in cols])
    return buf.getvalue()


def _rule_label(name: str) -> str:
    base, _, ent = name.partition("_")
    if name == "rule_failing_jobs":
        return "Scheduled jobs that keep failing"
    if base == "duplicates":
        return f"Duplicate {label(ent)}"
    if base == "tax":
        return f"GSTIN on India {label(ent.replace('ids_', ''))}"
    if base == "blocked":
        return f"Blocked or inactive {label(ent)}"
    return name.replace("rule_", "").replace("_", " ").capitalize()


# ---- state a step keeps in the item's folder (bigger than project.json should hold)

def keep(ctx, name: str, obj) -> None:
    d = ctx.dir / "w3"
    d.mkdir(exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps(obj, default=str), encoding="utf-8")


def kept(ctx, name: str, default=None):
    p = ctx.dir / "w3" / f"{name}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    except ValueError:
        return default


REQUIRED = {"customer": ("name", "country"), "supplier": ("name", "country"), "product": ("sku", "name"), "order": ("customer", "amount"), "contact": ("name", "email"),
            "worker": ("name",), "user": ("name", "email"), "part": ("key", "name"), "account": ("key", "name"), "deal": ("name",), "invoice": ("party", "amount")}
COMPARE_SKIP = {"key", "number", "created", "status", "modified", "last_signin", "members", "items"}


def _target(ctx, entity: str, creates: bool = True) -> tuple[dict, SysAdapter]:
    for c, a in systems(ctx):
        if (entity in a.CREATES) if creates else (entity in a.ENTITIES):
            return c, a
    raise wb.StepFailed(f"Pick a connection to a system that takes {label(entity)} (its scope must be ‘Read & write — with approval’ for the write at the end).")


def _match(planned: list[dict], landed: list[dict], results: list[dict] | None = None) -> dict:
    """ref -> the landed record: by the id the write returned, else by name and e-mail as the system holds them."""
    by_key = {str(r.get("key")): r for r in landed}
    by_name: dict[str, list] = {}
    for r in landed:
        by_name.setdefault(norm_name(r.get("name")), []).append(r)
    ids = {str(x.get("ref")): str(x.get("id")) for x in results or [] if x.get("ok") and x.get("id")}
    out = {}
    for p in planned:
        ref = str(p.get("ref"))
        hit = by_key.get(ids.get(ref, "\0"))
        if not hit:
            cands = by_name.get(norm_name(p.get("name")), [])
            hit = next((x for x in cands if not p.get("email") or str(x.get("email") or "").lower() == str(p["email"]).lower()), cands[0] if cands else None)
        if hit:
            out[ref] = hit
    return out


def reconcile(ctx, entity: str, planned: list[dict], landed_all: list[dict], results: list[dict] | None, tag: str, compare: list[str]) -> list[dict]:
    """What was asked for vs what the system now holds, record by record: counts, fingerprints and a field-by-field
    sample, on CSV snapshots in the item's folder (evidence one click away)."""
    m = _match(planned, landed_all, results)
    cols = ["ref"] + compare
    asked = [{"ref": str(p["ref"]), **{k: p.get(k) for k in compare}} for p in planned]
    landed = [{"ref": ref, **{k: r.get(k) for k in compare}} for ref, r in m.items()]
    fa, fl = snap(ctx, f"{tag}-asked-{entity}", asked, cols), snap(ctx, f"{tag}-landed-{entity}", landed, cols)
    A, L = {"source": "file", "file": fa}, {"source": "file", "file": fl}
    rows = [ctx.proof("row_count", label=f"{label(entity).capitalize()}: asked for vs now in the system", source=A, target=L)]
    if landed:
        rows.append(ctx.proof("checksum", label=f"{label(entity).capitalize()}: fingerprints per field", source=A, target=L, columns=compare))
        rows.append(ctx.proof("sample_diff", label=f"{label(entity).capitalize()}: every record field by field", source=A, target=L, keys=["ref"], n=500, columns=compare))
    return rows


def _compare_fields(recs: list[dict], target_rows: list[dict], mapped: list[str] | None = None) -> list[str]:
    have = {k for r in target_rows[:50] for k, v in r.items() if v not in (None, "")}
    fields = mapped or [k for k in (recs[0] if recs else {}) if k != "ref"]
    return [f for f in fields if f not in COMPARE_SKIP and f in have and any(r.get(f) not in (None, "") for r in recs)]


def verify_fn(spec: Spec) -> Callable:
    """The `verify` action of a step that wrote (Develop › Run, Migrate › Run): read the system back, reconcile."""
    @stepfn
    def verify(ctx):
        hs = writes(ctx, ctx.step_id)
        if not hs:
            raise wb.StepFailed("Nothing was written from this step yet.")
        h = hs[-1]
        if h.get("status") != "written":
            return {"summary": f"The change is {h.get('status')} — nothing to read back yet." + (" Approve it in the Validation queue first." if h.get("status") == "awaiting approval" else ""),
                    "data": {"checks": [{"name": "write", "label": "The approved write", "status": "skip", "detail": h.get("status") or ""}]}}
        load = kept(ctx, f"load-{ctx.step_id}") or {}
        c = ctx.connection(load["conn"])
        a = adapter_of(c)
        results = (h.get("result") or {}).get("results") or []
        ok_refs = {str(r.get("ref")) for r in results if r.get("ok")}
        checks = []
        for ent, recs in (load.get("entities") or {}).items():
            planned = [r for r in recs if str(r["ref"]) in ok_refs] if results else recs
            landed = ctx.seen.records(c, a, ent)
            compare = _compare_fields(planned, landed, load.get("compare", {}).get(ent))
            checks += reconcile(ctx, ent, planned, landed, results, ctx.step_id, compare)
            flow = ctx.get("flow_node")
            if flow:
                tgt = ctx.lineage_node("entity", a.label, f"{c['name']}:{a.ENTITIES[ent][0]}", label=f"{a.ENTITIES[ent][0]} · {c['name']}", own=False)
                ctx.lineage_edge(flow, tgt, "writes", {"records": len(planned), "approval": h.get("checkpoint")})
        failed = [r for r in results if not r.get("ok")]
        if failed:
            checks.append({"name": "refused", "label": f"Refused by {c['name']}", "status": "fail", "measured": len(failed), "expected": 0,
                           "detail": "; ".join(f"{r.get('ref')}: {r.get('error')}" for r in failed[:4])[:400], "evidence": ctx.evidence("Records the system refused", failed, kind="write", ok=False)})
        good = all(x["status"] == "pass" for x in checks)
        n = sum(len(v) for v in (load.get("entities") or {}).values())
        return {"summary": (f"Read back from {c['name']}: all {len(ok_refs) or n} record(s) are there and agree field by field." if good else
                            f"Read back from {c['name']}: {sum(1 for x in checks if x['status'] != 'pass')} check(s) disagree — see the evidence."),
                "data": {"checks": checks}, "counts": {"written": len(ok_refs), "refused": len(failed)}}
    return verify


def develop_work(spec: Spec, title: str, journey_names: tuple = ("Describe", "Shape", "Build", "Prove", "Ship", "Run")) -> wb.Work:
    d_, s_, b_, p_, sh_, r_ = journey_names

    @stepfn
    def describe(ctx):
        ent = ctx.scope.get("entity") or (spec.creates or spec.entities)[0]
        c, a = _target(ctx, ent)
        files = [f for f in ctx.files(UPLOADS)]
        if not files:
            raise wb.StepFailed(f"Upload the {label(ent)} to bring into {c['name']} (CSV or Excel).")
        cols, rows = upload_rows(ctx, files[0])
        if not rows:
            raise wb.StepFailed(f"{files[0]['name']} has no rows.")
        existing = ctx.seen.records(c, a, ent)
        snap(ctx, "target-before", existing, ENTITY[ent][1])
        keep(ctx, "source", {"file": files[0]["name"], "columns": cols, "rows": rows})
        ctx.put("develop", {"entity": ent, "conn": c["id"], "file": files[0]["name"], "columns": cols, "existing": len(existing)})
        src = ctx.lineage_node("file_drop", "upload", f"{ctx.id}:{files[0]['name']}", label=f"{files[0]['name']} (upload)", own=False)
        flow = ctx.lineage_node("flow", spec.system, f"Interface: {ctx.title}", label=f"Interface: {ctx.title}", properties={"entity": ent, "target": c["name"]})
        ctx.lineage_edge(src, flow, "feeds")
        ctx.put("flow_node", flow)
        return {"summary": f"{len(rows)} record(s) in {files[0]['name']} ({len(cols)} columns); {c['name']} ({a.label}) holds {len(existing)} {label(ent)} in {a.ENTITIES[ent][0]}.",
                "counts": {"records": len(rows), "columns": len(cols), "already there": len(existing)},
                "data": {"columns": ["Column", "First values"], "rows": [[k, ", ".join(str(r.get(k) or "") for r in rows[:3])] for k in cols]}}

    def columns(ctx):
        return [("", "— not mapped —")] + [(c, c) for c in (ctx.get("develop") or {}).get("columns") or []]

    def shape(ctx):
        dv = ctx.get("develop") or {}
        ent = dv["entity"]
        src = kept(ctx, "source") or {}
        have = {r["id"]: r for r in ctx.records(ctx.step_id)}
        sug = suggest_mapping(src.get("columns") or [], ENTITY[ent][1], src.get("rows") or [])
        recs = []
        for f in ENTITY[ent][1]:
            s, why = sug.get(f, ("", ""))
            rule = {"country": "iso2", "credit_limit": "number", "price": "number", "amount": "number", "created": "date", "date": "date"}.get(f, "trim")
            base = {"id": f, "field": f, "required": f in REQUIRED.get(ent, ()), "source": s, "constant": "", "rule": rule if s else "", "why": f"{why}: {s}" if s else ("needed" if f in REQUIRED.get(ent, ()) else "")}
            recs.append({**base, **{k: have[f][k] for k in ("source", "constant", "rule") if f in have}})
        missing = [r["field"] for r in recs if r["required"] and not (r["source"] or r["constant"])]
        return {"summary": f"{sum(1 for r in recs if r['source'] or r['constant'])} of {len(recs)} field(s) mapped from {dv['file']} — rules first: the column's own name, a known name for it, or what its values look like."
                           + (f" Still needed: {', '.join(missing)}." if missing else " Correct anything, then confirm the design."),
                "records": recs, "counts": {"mapped": sum(1 for r in recs if r["source"] or r["constant"]), "fields": len(recs)},
                "data": {"pairs": [{"from": r["source"] or (f"= {r['constant']}" if r["constant"] else "—"), "to": r["field"], "rule": dict(TRANSFORMS).get(r["rule"] or "", r["rule"]),
                                    "status": "mapped" if r["source"] else "constant" if r["constant"] else ("missing" if r["required"] else "not mapped")} for r in recs]},
                "items": [f"{r['field']} ← {r['source'] or r['constant'] or '—'}" for r in recs[:8]]}

    def validate_map(recs, ctx):
        cols = set((ctx.get("develop") or {}).get("columns") or [])
        out = [f"{r['field']} is needed: map a column or give a constant" for r in recs if r.get("required") and not (r.get("source") or r.get("constant"))]
        out += [f"{r['field']}: there is no column {r['source']!r} in the upload" for r in recs if r.get("source") and r["source"] not in cols]
        return out

    def build(ctx):
        dv = ctx.get("develop") or {}
        ent = dv["entity"]
        c = ctx.connection(dv["conn"])
        a = adapter_of(c)
        mapping = [r for r in ctx.records(s_.lower()) if r.get("source") or r.get("constant")]
        probs = validate_map(ctx.records(s_.lower()), ctx)
        if probs:
            raise wb.StepFailed("The confirmed mapping has problems: " + "; ".join(probs[:5]))
        src = kept(ctx, "source") or {}
        recs = map_rows(src.get("rows") or [], mapping)
        for i, r in enumerate(recs):
            r["ref"] = str(r.get("key") or r.get("number") or f"row-{i + 1}")
        recs = [a.prepare(c, ent, r) for r in recs]
        keep(ctx, "records", recs)
        payloads = [{"ref": r["ref"], "body": a.payload(ent, r)} for r in recs]
        import yaml
        ctx.output("mapping.yaml", yaml.safe_dump({"source": dv["file"], "target": {"system": c["name"], "platform": a.label, "object": a.ENTITIES[ent][0]},
                                                   "fields": [{"to": m["field"], "from": m.get("source") or None, "constant": m.get("constant") or None, "rule": m.get("rule") or "as is"} for m in mapping]},
                                                  sort_keys=False, allow_unicode=True), label="The field mapping (YAML)")
        ctx.output("payloads.json", json.dumps(payloads[:2000], indent=1, default=str), label=f"What would be sent to {a.label} (JSON)")
        ctx.output("interface.md", f"# Interface: {ctx.title}\n\nFrom {dv['file']} into {c['name']} ({a.label}), object {a.ENTITIES[ent][0]}.\n\n| Field | From | Rule |\n|---|---|---|\n"
                   + "".join(f"| {m['field']} | {m.get('source') or '= ' + str(m.get('constant'))} | {dict(TRANSFORMS).get(m.get('rule') or '', m.get('rule'))} |\n" for m in mapping)
                   + "\nEvery record is checked against the system's own rules before anything is written; the write is one change a named person approves, and Relay reads the system back afterwards.\n",
                   label="Interface specification (Markdown)")
        return {"summary": f"{len(recs)} record(s) built as {a.label} {a.ENTITIES[ent][0]} bodies; the mapping and the specification are in the outputs.",
                "counts": {"records": len(recs), "fields": len(mapping)}, "data": {"columns": ["Ref"] + [m["field"] for m in mapping][:7], "rows": [[r["ref"]] + [r.get(m["field"]) for m in mapping][:7] for r in recs[:200]]}}

    def prove(ctx):
        dv = ctx.get("develop") or {}
        ent = dv["entity"]
        recs = kept(ctx, "records") or []
        before = read_csv(ctx.dir / "data" / "target-before.csv") if (ctx.dir / "data" / "target-before.csv").exists() else []
        names = {norm_name(r.get("name")): r for r in before}
        emails = {str(r.get("email") or "").lower(): r for r in before if r.get("email")}
        numbers = {str(r.get("number")).strip().lower(): r for r in before if str(r.get("number") or "").strip()}      # a part / employee / customer number already used
        seen_n: dict[str, str] = {}
        tests = []
        tc = ctx.connection(dv["conn"])
        ta = adapter_of(tc)
        for r in recs:
            probs = value_problems(ent, r) + [f"{f} is empty" for f in REQUIRED.get(ent, ()) if r.get(f) in (None, "")] + ta.problems(tc, ent, r)
            hit = names.get(norm_name(r.get("name"))) or (emails.get(str(r.get("email") or "").lower()) if r.get("email") else None)
            if hit:
                probs.append(f"already in the system as {hit.get('name')} ({hit.get('key')}) — it would be a duplicate")
            elif str(r.get("number") or "").strip().lower() in numbers:
                other = numbers[str(r.get("number")).strip().lower()]
                probs.append(f"the number {r.get('number')} is already used by {other.get('name')} ({other.get('key')})")
            n = norm_name(r.get("name"))
            if n and n in seen_n:
                probs.append(f"the same as {seen_n[n]} in this upload")
            seen_n.setdefault(n, r["ref"])
            tests.append({"name": r["ref"], "label": r.get("name"), "status": "fail" if probs else "pass", "detail": "; ".join(probs) or "passes the system's rules"})
        ok_refs = [t["name"] for t in tests if t["status"] == "pass"]
        ctx.put("passing", ok_refs)
        rows = [ctx.proof("tests_run", label=f"Each record against {label(ent)}' rules (dry run, nothing written)", results=tests),
                {"name": "duplicates", "label": "None is already in the system", "status": "pass" if not any("duplicate" in t["detail"] for t in tests) else "fail",
                 "measured": sum(1 for t in tests if "duplicate" in t["detail"]), "expected": 0, "detail": "; ".join(f"{t['label']}: {t['detail']}" for t in tests if "duplicate" in t["detail"])[:400] or "no matches by name or e-mail"},
                ctx.proof("references_real", label="The target object exists on the system", refs=[adapter_of(ctx.connection(dv["conn"])).ENTITIES[ent][0]],
                          known=[o["object"] for o in adapter_of(ctx.connection(dv["conn"])).list_objects(ctx.connection(dv["conn"]))])]
        return {"summary": f"{len(ok_refs)} of {len(tests)} record(s) pass the dry run; {len(tests) - len(ok_refs)} would be refused or duplicate — only the passing ones go to the write.",
                "counts": {"pass": len(ok_refs), "fail": len(tests) - len(ok_refs)}, "data": {"checks": rows},
                "items": [f"{t['label']}: {t['detail']}" for t in tests if t["status"] == "fail"][:6]}

    def ship(ctx):
        dv = ctx.get("develop") or {}
        c = ctx.connection(dv["conn"])
        ok_refs = ctx.get("passing") or []
        n = len(kept(ctx, "records") or [])
        approver = db.user(ctx.st.get("approver") or "") or {}
        return {"summary": f"Go live: {len(ok_refs)} {label(dv['entity'])} into {c['name']}; {n - len(ok_refs)} left out by the dry run.",
                "data": {"items": [{"title": "What is written", "detail": f"{len(ok_refs)} new {label(dv['entity'])} in {adapter_of(c).ENTITIES[dv['entity']][0]} on {c['name']}"},
                                   {"title": "Left out", "detail": f"{n - len(ok_refs)} record(s) that failed the dry run (see Prove)"},
                                   {"title": "Then", "detail": "The write is one change in the Validation queue: nothing reaches the system until it is approved; Relay reads it back and reconciles."},
                                   {"title": "Named approval", "detail": approver.get("name") or "the owner of this work item"}]}}

    def run(ctx):
        dv = ctx.get("develop") or {}
        ent = dv["entity"]
        c = ctx.connection(dv["conn"])
        a = adapter_of(c)
        ok_refs = set(ctx.get("passing") or [])
        recs = [r for r in kept(ctx, "records") or [] if r["ref"] in ok_refs]
        if not recs:
            return {"summary": "Nothing passed the dry run, so nothing is written.", "data": {"checks": [{"name": "write", "label": "No write was requested", "status": "skip", "detail": "nothing passed the dry run"}]}}
        mapped = [m["field"] for m in ctx.records(s_.lower()) if m.get("source") or m.get("constant")]
        keep(ctx, f"load-{ctx.step_id}", {"conn": c["id"], "entities": {ent: recs}, "compare": {ent: [f for f in mapped if f not in COMPARE_SKIP]}})
        cp = request_write(ctx, c, a.ENTITIES[ent][0], [{"op": "create", "entity": ent, "ref": r["ref"], "data": a.payload(ent, r)} for r in recs],
                           f"Create {len(recs)} {label(ent)} in {c['name']}", [f"{r['ref']}: {r.get('name') or r.get('number')}" for r in recs[:10]] + ([f"… and {len(recs) - 10} more"] if len(recs) > 10 else []))
        return {"summary": f"{len(recs)} {label(ent)} wait for the write approval in the Validation queue; once written, Relay reads {c['name']} back and reconciles every record.",
                "counts": {"to write": len(recs)}, "data": {"checks": [pending(cp, c, len(recs))]}}

    return wb.Work(title=title, needs_source=True, fields=[wb.Field("entity", "What to bring in", "select", options=[(e, label(e).capitalize()) for e in spec.creates], default=(spec.creates or ("",))[0],
                                                                       help="The records in your upload, created in the system you pick (its scope must allow writes with approval).")],
                   steps={
        d_: wb.Step(kind="platform", run=describe, agent="Reader", text=f"The upload is read and the {spec.noun} it goes into shows what it already holds — read-only"),
        s_: wb.Step(kind="deterministic", run=shape, view="mapping", agent="Mapper", confirm="the field mapping, side by side with the upload's columns",
                    edit=wb.Edit(columns=[wb.Column("field", "Field", readonly=True), wb.Column("source", "From column", "select", options=columns), wb.Column("constant", "Or a constant"),
                                          wb.Column("rule", "Rule", "select", options=TRANSFORMS), wb.Column("why", "Why Relay suggests it", readonly=True)],
                                 add=False, remove=False, validate=validate_map, label="field"),
                    text="Each field of the target suggested from the upload — the column's own name, a known name, or its values — you correct it in place"),
        b_: wb.Step(kind="deterministic", run=build, agent="Interface builder", text="The mapping applied to every record: the bodies the system's API takes, the mapping and the specification"),
        p_: wb.Step(kind="proof", run=prove, view="gates", agent="Prover", back_to=s_.lower(), text="A dry run: every record against the system's own rules and what it already holds — nothing is written"),
        sh_: wb.Step(kind="person", run=ship, view="plan", approver=True, back_to=s_.lower(), text="The named approver confirms what goes in (a send back returns to the mapping)"),
        r_: wb.Step(kind="platform", run=run, view="gates", agent="Loader", text="One write the approver accepts in the Validation queue; then Relay reads the system back and reconciles record by record",
                    actions={"verify": wb.Action(label="Read back and reconcile", kind="platform", run=verify_fn(spec), agent="Reconciler",
                                                 help="Reads the system again and compares every written record with what was asked for.")}),
    })


# ================================================================== Fix / change

def _brief_words(ctx) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Za-z0-9_\-]{4,}", ctx.brief or "")}


EXPLAIN = """Read WORK.md, then diagnose.json in this folder: the jobs whose last runs failed with an error no rule of Relay
recognises — each with its run history and the vendor's own log lines. Write diagnosis.yaml:

jobs:
  <job id>:
    cause: "one sentence: why it fails, taken from the log lines"
    fix: "one sentence: what a person changes, then the job runs again"

Only the job ids in diagnose.json. Quote what the log says; never invent a table, a field, a number or a setting it
does not name. If the log does not say, write cause: "the log does not say" and fix: "ask the job's owner"."""


def _explain_prompt(ctx) -> str:
    (ctx.dir / "diagnose.json").write_text(json.dumps({"jobs": ctx.get("unknown") or []}, indent=1, default=str), encoding="utf-8")
    return EXPLAIN


def _explain_check(ctx) -> list[str]:
    import yaml
    p = ctx.dir / "diagnosis.yaml"
    if not p.exists():
        return ["diagnosis.yaml was not written"]
    try:
        y = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        return [f"diagnosis.yaml does not parse: {str(e).splitlines()[0]}"]
    jobs = y.get("jobs") if isinstance(y, dict) else None
    if not isinstance(jobs, dict):
        return ["diagnosis.yaml needs a mapping `jobs:` from job id to cause and fix"]
    known = {str(u["job"]) for u in ctx.get("unknown") or []}
    out = [f"unknown job id {k} (only the ids in diagnose.json)" for k in jobs if str(k) not in known]
    out += [f"job {k}: give both a cause and a fix (one sentence each)" for k, v in jobs.items() if not isinstance(v, dict) or not str(v.get("cause") or "").strip() or not str(v.get("fix") or "").strip()]
    return out


def _explain_after(ctx, res) -> dict:
    import yaml
    jobs = (yaml.safe_load((ctx.dir / "diagnosis.yaml").read_text(encoding="utf-8")) or {}).get("jobs") or {}
    props = ctx.get("proposals") or []
    for u in ctx.get("unknown") or []:
        d = jobs.get(u["job"]) or jobs.get(str(u["job"]))
        if not d:
            continue
        for p in props:
            if p.get("key") == u["job"] and p.get("action") == "manual":
                p.update(why=f"Relay's reading (check it): {d['fix']}", cause=f"Relay's reading: {d['cause']}", drafted_by="agent")
    ctx.put("proposals", props)
    data = dict((ctx.result(ctx.step_id) or {}).get("data") or {})
    checks = [dict(c) for c in data.get("checks") or []]
    for c in checks:
        job = str(c.get("name", "")).split("job:", 1)[-1]
        if job in jobs:
            c["detail"] = f"Relay's reading of the log (check it): {jobs[job]['cause']} Fix: {jobs[job]['fix']}"
    ctx.evidence("Relay's reading of the logs", {"diagnosis": jobs, "summary": res.get("text") or ""}, kind="agent", ok=True)
    return {"summary": f"Relay read {len(jobs)} log(s) no rule recognised and drafted a cause and a fix for each — check them before you confirm.", "data": {"checks": checks}}


def change_work(spec: Spec, title: str) -> wb.Work:
    def assess_items(u):
        rows = db.q("SELECT id, title FROM wb_items WHERE module = ? AND work = 'assess' AND status = 'done' ORDER BY updated DESC LIMIT 50", (spec.module,))
        from .. import auth
        vis = auth.access_map(u, [r["id"] for r in rows])
        return [("", "No — from the request")] + [(r["id"], r["title"]) for r in rows if r["id"] in vis]

    @stepfn
    def request(ctx):
        words = _brief_words(ctx)
        targets = []
        for c, a in systems(ctx):
            runs = ctx.seen.runs(c, a) if type(a).runs is not SysAdapter.runs else []
            text = (ctx.brief or "").lower()
            for job in dict.fromkeys(r["job"] for r in runs):
                lbl = next((r.get("label") for r in runs if r["job"] == job), "") or ""
                lw = {w for w in re.findall(r"[a-z0-9]{4,}", lbl.lower())}
                if re.search(r"(?<![\w-])" + re.escape(job.lower()) + r"(?![\w-])", text) or (lbl and lbl.lower() in text) or (lw and len(lw & words) / len(lw) >= 0.6):
                    targets.append({"kind": "job", "conn": c["id"], "system": c["name"], "job": job, "label": lbl or job})
        src = ctx.scope.get("from_item")
        if src:
            try:
                prev = wb._load(src)
                for s in prev["steps"]:
                    if s["id"] == "findings":
                        for f in s.get("records") or []:
                            if f.get("decision") != "ignore" and f.get("work") == "change" and not any(t.get("finding") == f["id"] for t in targets):
                                conn = next((c["id"] for c, a in systems(ctx) if c["name"] == f["system"]), None)
                                if conn:
                                    targets.append({"kind": "finding", "conn": conn, "system": f["system"], "finding": f["id"], "label": f["what"][:160], "data": f})
            except (KeyError, FileNotFoundError):
                pass
        for c, a in systems(ctx):                     # records the request names (a duplicate, a customer)
            for ent in spec.entities:
                if ent not in a.ENTITIES or not any(w in (ctx.brief or "").lower() for w in ("duplicate", label(ent)[:-1])):
                    continue
                rows = ctx.seen.records(c, a, ent)
                for g in dupes(rows):
                    if any(norm_name(r["name"]) in norm_name(ctx.brief) or any(w in norm_name(r["name"]).split() for w in words) for r in g):
                        targets.append({"kind": "duplicate", "conn": c["id"], "system": c["name"], "entity": ent, "label": " / ".join(str(r["name"]) for r in g),
                                        "keys": [str(r["key"]) for r in g]})
        for sig in spec.signatures:                   # an error pasted into the request (a ticket's text) names its system
            hit = sig.match(ctx.brief or "") if sig.kinds else None
            if hit and not any(t["kind"] == "job" for t in targets):
                for c, a in systems(ctx, sig.kinds):
                    targets.append({"kind": "error", "conn": c["id"], "system": c["name"], "label": hit.group(0)[:160], "error": (ctx.brief or "")[:2000], "signature": sig.pattern})
        dedup = {json.dumps({k: v for k, v in t.items() if k != "data"}, sort_keys=True): t for t in targets}
        targets = list(dedup.values())
        ctx.put("targets", targets)
        if not targets:
            raise wb.StepFailed("The request names no job, record or finding Relay can find on the connected systems: name the job (e.g. its id) or the record, or start from an assessment.")
        return {"summary": f"The request names {len(targets)} thing(s) to change: " + "; ".join(f"{t['label']} ({t['system']})" for t in targets[:4]) + ".",
                "counts": {"targets": len(targets)}, "data": {"text": (ctx.brief or "(no request text)") + "\n\nRelay found in it:\n" + "\n".join(f"- {t['kind']}: {t['label']} on {t['system']}" for t in targets)}}

    @stepfn
    def diagnose(ctx):
        rules = learned(spec.module)
        checks, props, unknown = [], [], []
        for t in ctx.get("targets") or []:
            c = ctx.connection(t["conn"])
            a = adapter_of(c)
            if t["kind"] == "job" or (t["kind"] == "finding" and t["data"].get("entity") == "jobs"):
                job = t.get("job") or t["data"]["record"]
                runs = [r for r in ctx.seen.runs(c, a) if r["job"] == job]
                last = runs[0] if runs else None
                log = a.job_log(ctx.seen.api(c, a), last) if last else []
                text = " ".join([str(last.get("error") or "")] + log) if last else ""
                rule = next((r for r in rules if re.search(r["signature"], text or "", re.I)), None)
                sig = next((s for s in spec.signatures if s.match(text)), None)
                eid = ctx.evidence(f"Run history and log of {job}", {"runs": runs[:14], "log": log}, kind="runs", ok=bool(last and last["status"] == "succeeded"))
                if not last or last["status"] == "succeeded":
                    checks.append({"name": f"job:{job}", "label": f"{t['label']} on {c['name']}", "status": "pass", "detail": "the last run succeeded — nothing to fix", "evidence": eid})
                    continue
                cause = (rule or {}).get("cause") or (sig.cause if sig else "")
                fix = (rule or {}).get("fix") or (sig.fix if sig else "Read the log; fix the cause; run the job again.")
                if not cause:
                    unknown.append({"job": job, "label": t["label"], "system": c["name"], "runs": [{k: r.get(k) for k in ("id", "started", "status", "error")} for r in runs[:6]], "log": log[:40]})
                checks.append({"name": f"job:{job}", "label": f"{t['label']} on {c['name']}", "status": "fail" if cause else "warn", "severity": "high",
                               "measured": f"{sum(1 for r in runs[:5] if r['status'] != 'succeeded')} of the last {min(5, len(runs))} runs failed", "expected": "succeeded",
                               "detail": (f"Cause: {cause} Fix: {fix}" if cause else f"No known cause for “{(last.get('error') or '')[:160]}” — a person diagnoses it.") + (" (a rule Relay learned)" if rule else ""),
                               "evidence": eid})
                proposed = []
                if rule:
                    db.run("UPDATE w3_rules SET uses = uses + 1 WHERE id = ?", (rule["id"],))
                if sig and sig.propose:
                    proposed = sig.propose(ctx, c, a, ctx.seen.api(c, a), last) or []
                elif rule:
                    proposed = [{**op, "id": f"{slug(job)}-{i}", "why": f"learned from {rule['learned_from']}"} for i, op in enumerate(rule["ops"])]
                if not any(p.get("action") == "manual" for p in proposed) and (not proposed or not any(p.get("action") == "rerun" for p in proposed)):
                    if not proposed and fix:
                        proposed.append({"action": "manual", "why": fix, "field": "", "value": ""})
                    if type(a).op_rerun is not SysAdapter.op_rerun:
                        proposed.append({"action": "rerun", "job": job, "run": last.get("id") or "", "why": "run it again once the cause is fixed"})
                for i, p in enumerate(proposed):
                    props.append({"id": p.get("id") or f"{slug(job)}-{i}", "include": True, "system": c["name"], "conn": c["id"], "entity": p.get("entity") or "jobs", "key": p.get("key") or job,
                                  "label": p.get("label") or t["label"], "signature": (sig.pattern if sig else (rule or {}).get("signature")) or "", "cause": cause, "fix": fix, **p})
            elif t["kind"] == "error":
                sig = next((s for s in spec.signatures if s.pattern == t["signature"]), None)
                rule = next((r for r in rules if re.search(r["signature"], t["error"] or "", re.I)), None)
                eid = ctx.evidence("The error in the request", {"text": t["error"]}, kind="request", ok=False)
                checks.append({"name": f"error:{slug(t['label'])}", "label": f"{t['label']} on {c['name']}", "status": "fail", "severity": "high",
                               "detail": f"Cause: {sig.cause} Fix: {sig.fix}" + (" (a rule Relay learned)" if rule else ""), "evidence": eid})
                proposed = (sig.propose(ctx, c, a, ctx.seen.api(c, a), {"error": t["error"]}) if sig and sig.propose else []) or [{"action": "manual", "why": sig.fix if sig else "a person fixes it"}]
                for i, p in enumerate(proposed):
                    props.append({"id": f"{slug(t['label'])}-{i}", "include": True, "system": c["name"], "conn": c["id"], "entity": p.get("entity") or "jobs", "key": p.get("key") or "",
                                  "label": p.get("label") or t["label"], "signature": t["signature"], "cause": sig.cause if sig else "", "fix": sig.fix if sig else "", **p})
            elif t["kind"] == "finding" and t["data"].get("proposals"):
                f = t["data"]
                checks.append({"name": f"finding:{slug(f['id'])}", "label": f"{f['what'][:160]}", "status": "fail" if f["severity"] == "high" else "warn", "severity": f["severity"],
                               "detail": f"Fix: {f.get('fix') or ''}", "evidence": f.get("evidence")})
                for i, p in enumerate(f["proposals"]):
                    props.append({"id": f"{slug(f['id'])}-{i}", "include": True, "system": c["name"], "conn": c["id"], "signature": f["kind"], "cause": f["what"], "fix": f.get("fix") or "", **p})
            elif t["kind"] in ("duplicate",) or (t["kind"] == "finding" and t["data"].get("kind") == "duplicate"):
                ent = t.get("entity") or t["data"]["entity"]
                keys = t.get("keys") or t["data"].get("keys") or []
                rows = {str(r["key"]): r for r in ctx.seen.records(c, a, ent)}
                group = [rows[k] for k in keys if k in rows]
                if len(group) < 2:
                    checks.append({"name": f"dup:{t['label']}", "label": t["label"], "status": "pass", "detail": "no longer a duplicate"})
                    continue
                group.sort(key=lambda r: (str(r.get("created") or ""), str(r.get("key"))))
                survivor, others = group[0], group[1:]
                eid = ctx.evidence(f"The duplicate {label(ent)}", group, kind="records", ok=False)
                checks.append({"name": f"dup:{t['label']}", "label": f"Duplicate {label(ent)[:-1]}: {t['label']}", "status": "fail", "severity": "medium", "measured": len(group), "expected": 1,
                               "detail": f"Keep {survivor['name']} ({survivor['key']}, the older record); block {', '.join(str(o['name']) + ' (' + str(o['key']) + ')' for o in others)}.", "evidence": eid})
                for o in others:
                    for fname, v in (a.DEACTIVATE.get(ent) or {}).items():
                        props.append({"id": f"dup-{slug(o['key'])}-{fname}", "include": True, "system": c["name"], "conn": c["id"], "action": "deactivate", "entity": ent, "key": str(o["key"]),
                                      "label": str(o["name"]), "field": fname, "value": v, "before": "", "why": f"duplicate of {survivor['name']} ({survivor['key']})",
                                      "signature": "duplicate", "cause": "the same customer was keyed twice", "fix": "block the newer record"})
                    if not a.DEACTIVATE.get(ent):                # the platform merges in its own screens (no API Relay may call): a step for a person
                        props.append({"id": f"dup-{slug(o['key'])}-merge", "include": True, "system": c["name"], "conn": c["id"], "action": "manual", "entity": ent, "key": str(o["key"]),
                                      "label": str(o["name"]), "field": "", "value": "", "before": "", "why": f"merge {o['name']} into {survivor['name']} ({survivor['key']}) in {a.label}'s duplicate management",
                                      "signature": "duplicate", "cause": "the same customer was keyed twice", "fix": "merge the newer record into the older one"})
            elif t["kind"] == "finding" and t["data"].get("kind") in ("missing_tax", "invalid_tax"):
                ent = t["data"]["entity"]
                for k in t["data"].get("keys") or []:
                    props.append({"id": f"tax-{slug(k)}", "include": True, "system": c["name"], "conn": c["id"], "action": "update", "entity": ent, "key": k, "label": t["data"]["record"],
                                  "field": "tax_id", "value": "", "before": "", "why": t["data"]["what"], "signature": t["data"]["kind"], "cause": t["data"]["what"], "fix": t["data"]["fix"]})
                checks.append({"name": f"tax:{t['label']}", "label": t["label"], "status": "warn", "detail": "the right GSTIN comes from the customer — a person types it in Fix"})
        ctx.put("proposals", props)
        ctx.put("unknown", unknown)
        if not checks:
            raise wb.StepFailed("Nothing to diagnose.")
        return {"summary": f"{sum(1 for c in checks if c['status'] != 'pass')} problem(s) diagnosed; {len(props)} change(s) proposed for a person to confirm — nothing has changed yet.",
                "counts": {"problems": sum(1 for c in checks if c["status"] != "pass"), "changes": len(props)}, "data": {"checks": checks},
                "items": [c["detail"][:200] for c in checks if c["status"] != "pass"][:6]}

    def fix(ctx):
        have = {r["id"]: r for r in ctx.records(ctx.step_id)}
        recs = [{**p, **({k: have[p["id"]][k] for k in ("include", "field", "value") if k in have[p["id"]]} if p["id"] in have else {})} for p in ctx.get("proposals") or []]
        return {"summary": f"{len(recs)} proposed change(s): correct a value, untick what should not happen, then confirm. Nothing reaches the system until the approver releases it.",
                "records": recs, "counts": {"changes": sum(1 for r in recs if r.get("include"))},
                "data": {"columns": ["Do it", "System", "Change", "Record", "Field", "New value", "Why"],
                         "rows": [["yes" if r.get("include") else "no", r["system"], r["action"], r.get("label") or r.get("key"), r.get("field") or "", r.get("value") if r.get("value") not in (None, "") else "", r.get("why") or ""] for r in recs]}}

    def validate_fix(recs, ctx):
        out = []
        for r in recs:
            if not r.get("include"):
                continue
            a = adapter_of(ctx.connection(r["conn"]))
            if r["action"] == "create":
                if not a or r.get("entity") not in a.CREATES:
                    out.append(f"{r.get('label')}: {a.label if a else 'the system'} does not create {label(r.get('entity', ''))} through Relay")
                elif not r.get("key"):
                    out.append(f"{r.get('label')}: give the name of the new record")
                elif r.get("field") and r.get("value") in (None, ""):
                    out.append(f"{r.get('label')}: give the {r['field']}")
            elif r["action"] in ("update", "deactivate"):
                allowed = set((a.WRITABLE.get(r.get("entity")) or {})) if a else set()
                if r.get("field") not in allowed:
                    out.append(f"{r.get('label')}: {a.label if a else 'the system'} lets Relay change only {', '.join(sorted(allowed)) or 'nothing'} on {label(r.get('entity', ''))}")
                elif r.get("value") in (None, ""):
                    out.append(f"{r.get('label')}: give the new {r['field']}")
                elif r["field"] == "tax_id" and not GSTIN.match(str(r["value"])):
                    out.append(f"{r.get('label')}: {r['value']} does not have the GSTIN format")
        return out

    @stepfn
    def prove(ctx):
        recs = [r for r in ctx.records("fix") if r.get("include")]
        probs = validate_fix(recs, ctx)
        if probs:
            raise wb.StepFailed("The confirmed changes have problems: " + "; ".join(probs[:5]))
        checks, before = [], []
        for r in recs:
            c = ctx.connection(r["conn"])
            a = adapter_of(c)
            if r["action"] in ("update", "deactivate"):
                rows = {str(x["key"]): x for x in ctx.seen.records(c, a, r["entity"])}
                cur = rows.get(str(r["key"]))
                was = cur.get(r["field"]) if cur else None
                before.append({"record": r.get("label"), "key": r["key"], "field": r["field"], "now": was, "after": r["value"]})
                probs = value_problems(r["entity"], {**(cur or {}), r["field"]: r["value"]}) if cur and r["field"] in ("email", "country", "currency", "tax_id", "credit_limit") else []
                probs += a.field_problems(r["entity"], r["field"], r["value"]) if cur else []
                checks.append({"name": r["id"], "label": f"{r.get('label')}: {r['field']} → {r['value']}", "status": "fail" if not cur or probs else "pass",
                               "detail": ("the record is not on the system any more" if not cur else "; ".join(probs) or f"the record exists; {r['field']} is {was!r} now"), "measured": was, "expected": r["value"]})
            elif r["action"] == "create":
                have = {str(x.get("key")).lower() for x in ctx.seen.records(c, a, r["entity"])} | {str(x.get("name") or "").lower() for x in ctx.seen.records(c, a, r["entity"])}
                there = str(r["key"]).lower() in have
                checks.append({"name": r["id"], "label": f"Create {label(r['entity'])[:-1]} {r['key']}" + (f" ({r['field']}: {r['value']})" if r.get("field") else ""), "status": "fail" if there else "pass",
                               "detail": "it is already there — nothing to create" if there else f"{c['name']} does not hold it yet", "measured": "present" if there else "absent", "expected": "absent"})
            elif r["action"] == "rerun":
                runs = [x for x in ctx.seen.runs(c, a) if x["job"] == r["job"]]
                checks.append({"name": r["id"], "label": f"Run {r.get('label') or r['job']} again", "status": "pass" if runs and runs[0]["status"] != "succeeded" else "warn",
                               "detail": "its last run failed: a run after the fix shows whether it holds" if runs and runs[0]["status"] != "succeeded" else "its last run did not fail"})
            else:
                checks.append({"name": r["id"], "label": f"A person does: {r.get('why')}"[:200], "status": "warn", "detail": "outside what Relay changes through the API — done by a person before the release"})
        eid = ctx.evidence("Before and after", before, kind="diff", ok=True) if before else None
        if eid:
            for x in checks:
                x.setdefault("evidence", eid)
        return {"summary": f"Dry run of {len(recs)} change(s): {sum(1 for x in checks if x['status'] == 'pass')} ready, {sum(1 for x in checks if x['status'] == 'warn')} need a person, "
                           f"{sum(1 for x in checks if x['status'] == 'fail')} cannot apply — nothing was changed.", "data": {"checks": checks},
                "counts": {"ready": sum(1 for x in checks if x["status"] == "pass"), "fail": sum(1 for x in checks if x["status"] == "fail")}}

    def approve(ctx):
        recs = [r for r in ctx.records("fix") if r.get("include")]
        by: dict[str, list] = {}
        for r in recs:
            by.setdefault(r["system"], []).append(r)
        return {"summary": f"Release {sum(1 for r in recs if r['action'] != 'manual')} change(s) on {len(by)} system(s)" + (f"; {sum(1 for r in recs if r['action'] == 'manual')} step(s) for a person first." if any(r["action"] == "manual" for r in recs) else "."),
                "data": {"items": [{"title": s, "detail": "; ".join(f"{r['action']} {r.get('label') or r.get('key')}" + (f" · {r['field']} = {r['value']}" if r.get("field") else "") for r in rs)} for s, rs in by.items()]
                         + [{"title": "Then", "detail": "Each system's changes are one write in the Validation queue; Relay checks them on the system afterwards and keeps the fix as a rule."}]}}

    def learn_step(ctx):
        recs = [r for r in ctx.records("fix") if r.get("include") and r["action"] != "manual"]
        by: dict[str, list] = {}
        for r in recs:
            by.setdefault(r["conn"], []).append(r)
        cps = []
        for cid, rs in by.items():
            c = ctx.connection(cid)
            a = adapter_of(c)
            ops = []
            for r in rs:
                if r["action"] == "rerun":
                    ops.append({"op": "rerun", "job": r["job"], "run": r.get("run") or "", "ref": r["id"]})
                elif r["action"] == "create":
                    ops.append({"op": "create", "entity": r["entity"], "ref": r["id"], "data": a.payload(r["entity"], {"key": r["key"], "name": r["key"], **({r["field"]: r["value"]} if r.get("field") else {})})})
                else:
                    ops.append({"op": r["action"], "entity": r["entity"], "key": r["key"], "data": {r["field"]: r["value"]}, "ref": r["id"]})
            cps.append(request_write(ctx, c, "change", ops, f"Release {len(ops)} change(s) on {c['name']}", [f"{r['action']}: {r.get('label') or r.get('key')}" + (f" · {r['field']} = {r['value']}" if r.get("field") else "") for r in rs]))
        keep(ctx, f"change-{ctx.step_id}", {"changes": recs})
        if not cps:
            return {"summary": "Nothing to write: the changes are steps a person does.", "data": {"checks": [{"name": "write", "label": "No write was requested", "status": "skip", "detail": "every change is a step for a person"}]}}
        return {"summary": f"{len(cps)} write(s) wait for approval in the Validation queue; once written, Relay checks each change on the system and keeps the fix as a rule.",
                "counts": {"writes": len(cps), "changes": len(recs)}, "data": {"checks": [pending(cp, ctx.connection(cid), len(rs)) for cp, (cid, rs) in zip(cps, by.items())]}}

    @stepfn
    def verify_change(ctx):
        st = kept(ctx, f"change-{ctx.step_id}") or {}
        hs = writes(ctx, ctx.step_id)
        if not hs or not any(h.get("status") == "written" for h in hs):
            return {"summary": "Nothing has been written yet — approve the change in the Validation queue first.", "data": {"checks": []}}
        checks, worked = [], {}
        for r in st.get("changes") or []:
            c = ctx.connection(r["conn"])
            a = adapter_of(c)
            h = next((x for x in hs if x.get("connection") == c["name"]), None)
            if not h or h.get("status") != "written":
                checks.append({"name": r["id"], "label": f"{r.get('label')}", "status": "skip", "detail": f"its write is {h.get('status') if h else 'not requested'}"})
                continue
            res = next((x for x in (h.get("result") or {}).get("results") or [] if x.get("ref") == r["id"]), {})
            if not res.get("ok"):
                checks.append({"name": r["id"], "label": f"{r.get('label')}", "status": "fail", "detail": f"the system refused it: {res.get('error') or 'no answer'}"})
                continue
            if r["action"] == "create":
                rows = a.records(ctx.seen.api(c, a), r["entity"])
                got = next((x for x in rows if str(x.get("key")).lower() == str(r["key"]).lower() or str(x.get("name") or "").lower() == str(r["key"]).lower()), None)
                checks.append({"name": r["id"], "label": f"{r.get('label')}", "status": "pass" if got else "fail", "measured": "present" if got else "absent", "expected": "present",
                               "detail": f"{c['name']} now holds {r['key']}" + (f" under {got.get('group')}" if got and got.get("group") else "") if got else "the system does not show it"})
                worked.setdefault(r.get("signature") or "", []).append(bool(got))
                continue
            if r["action"] == "rerun":
                api = ctx.seen.api(c, a)
                s = {"status": "unknown"}
                for _ in range(8):
                    s = a.op_status(api, res)
                    if s.get("status") in ("succeeded", "failed", "warning", "cancelled"):
                        break
                good = s.get("status") == "succeeded"
                checks.append({"name": r["id"], "label": f"{r.get('label') or r['job']} ran again", "status": "pass" if good else "fail", "measured": s.get("status"), "expected": "succeeded",
                               "detail": "the run after the fix succeeded" if good else f"it still fails: {s.get('error') or s.get('status')}"})
                worked.setdefault(r.get("signature") or "", []).append(good)
            else:
                rows = {str(x["key"]): x for x in a.records(ctx.seen.api(c, a), r["entity"])}
                cur = rows.get(str(r["key"])) or {}
                now = cur.get(r["field"])
                good = str(now).lower() == str(r["value"]).lower() or (r["action"] == "deactivate" and str(cur.get("status")) in ("blocked", "inactive", "disabled"))
                checks.append({"name": r["id"], "label": f"{r.get('label')}: {r['field']}", "status": "pass" if good else "fail", "measured": now if now is not None else cur.get("status"), "expected": r["value"],
                               "detail": "the system holds the new value" if good else "the system does not show the change"})
                worked.setdefault(r.get("signature") or "", []).append(good)
        learned_ids = []
        for sig, oks in worked.items():
            if sig and sig not in ("duplicate", "missing_tax", "invalid_tax") and oks and all(oks):
                rs = [r for r in st.get("changes") or [] if r.get("signature") == sig]
                ops = [{k: r.get(k) for k in ("action", "entity", "field", "value", "job", "why") if r.get(k) not in (None, "")} for r in rs if r["action"] != "deactivate"]
                learned_ids.append(learn(spec.module, sig, rs[0].get("cause") or "", rs[0].get("fix") or "", ops, ctx.id, ctx.who))
        good = all(x["status"] == "pass" for x in checks if x["status"] != "skip")
        return {"summary": ("Checked on the system: every change holds." if good else "Checked on the system: some changes do not hold — see the checks.") + (f" {len(learned_ids)} fix(es) kept as rules for next time." if learned_ids else ""),
                "data": {"checks": checks}, "counts": {"rules learned": len(learned_ids)}}

    return wb.Work(title=title, needs_source=True, fields=[wb.Field("from_item", "Start from an assessment", "select", options=assess_items, help="Its kept findings become what to change.")], steps={
        "Request": wb.Step(kind="platform", run=request, view="text", agent="Request reader", text="The request in plain words (or an assessment's findings): Relay finds the jobs and records it names on the connected systems"),
        "Diagnose": wb.Step(kind="platform", run=diagnose, view="gates", agent="Diagnoser", text="Run history and logs read; the vendor's error matched to a known cause (and to the fixes Relay learned) — you confirm the diagnosis",
                            actions={"explain": wb.Action(label="Ask Relay to read the unknown errors", kind="agent", prompt=_explain_prompt, check=_explain_check, after=_explain_after,
                                                          agent="Log reader", help="Only for failures no rule recognises: the agent reads their logs and drafts a cause and a fix for you to check.")}),
        "Fix": wb.Step(kind="person", run=fix, edit=wb.Edit(columns=[wb.Column("include", "Do it", "bool"), wb.Column("system", "System", readonly=True), wb.Column("action", "Change", readonly=True),
                                                                   wb.Column("label", "Record", readonly=True), wb.Column("field", "Field"), wb.Column("value", "New value"), wb.Column("why", "Why", readonly=True)],
                                                           add=False, remove=False, validate=validate_fix, label="change"),
                       confirm="the changes with their values", text="The proposed changes — a field on a record, a job run again, a step for a person — you correct and confirm them"),
        "Prove": wb.Step(kind="proof", run=prove, view="gates", agent="Prover", back_to="fix", confirm="the dry run found something the system would refuse — send it back to Fix",
                         confirm_if=lambda ctx, out: any(x.get("status") == "fail" for x in (out.get("data") or {}).get("checks") or []),
                         text="A dry run against the system now: the records exist, the values pass its rules, the before and after side by side"),
        "Approve": wb.Step(kind="person", run=approve, view="plan", approver=True, back_to="fix", text="The named approver releases the change (a send back returns to Fix)"),
        "Learn": wb.Step(kind="platform", run=learn_step, view="gates", agent="Releaser", text="One write per system, approved in the Validation queue; Relay checks each change on the system and keeps the fix as a rule for next time",
                         actions={"verify": wb.Action(label="Check on the system", kind="platform", run=verify_change, agent="Reconciler", help="Reads the changed records and the job runs again.")}),
    })


# ================================================================== Migrate

def _target_options(spec_kinds: Callable) -> Callable:
    def opts(u):
        out = [("", "Pick the system to move into")]
        for c in connectors.mine(u["id"]):
            a = adapter_of({"kind": c["kind"]})
            if a and c["kind"] in spec_kinds():
                out.append((c["id"], f"{c['name']} · {c['label']}"))
        return out
    return opts


def migrate_work(spec: Spec, title: str, kinds: Callable) -> wb.Work:
    def target(ctx) -> tuple[dict, SysAdapter]:
        tid = ctx.scope.get("target") or ""
        if not tid:
            raise wb.StepFailed("Pick the system to move into (Target).")
        c = ctx.connection(tid)
        a = adapter_of(c)
        if not a:
            raise wb.StepFailed(f"{c['name']} is not a system this module moves records into.")
        return c, a

    def wanted(ctx) -> set[str] | None:
        t = (ctx.scope.get("entities") or "").lower()
        hits = {e for e in spec.entities if e in t or label(e) in t}
        return hits or None

    @stepfn
    def discover(ctx):
        tc, ta = target(ctx)
        want = wanted(ctx)
        found: dict[str, list] = {}
        srcs = []
        for c, a in systems(ctx):
            if c["id"] == tc["id"]:
                continue
            for ent in spec.entities:
                if ent in a.ENTITIES and ent in ta.CREATES and (want is None or ent in want):
                    rows = ctx.seen.records(c, a, ent)
                    for r in rows:
                        r["_source"] = c["name"]
                    found.setdefault(ent, []).extend(rows)
                    srcs.append((c["name"], a.label, ent, len(rows)))
        for f in ctx.files(UPLOADS):
            ent, recs, _ = from_upload(ctx, spec, f)
            if ent and ent in ta.CREATES and (want is None or ent in want):
                for r in recs:
                    r["_source"] = f["name"]
                found.setdefault(ent, []).extend(recs)
                srcs.append((f["name"], "Export (upload)", ent, len(recs)))
        if not found:
            raise wb.StepFailed(f"Nothing to move: the sources hold none of what {tc['name']} ({ta.label}) takes ({', '.join(label(e) for e in ta.CREATES) or 'nothing'}).")
        rows_out, plan = [], {}
        for ent, rows in found.items():
            for r in rows:
                r["ref"] = f"{slug(r['_source'])}:{r.get('key')}"
            snap(ctx, f"src-{ent}", rows, ["ref"] + ENTITY[ent][1] + ["_source"])
            there = ctx.seen.records(tc, ta, ent)
            snap(ctx, f"tgt-before-{ent}", there, ENTITY[ent][1])
            names = {norm_name(r.get("name")) for r in there}
            plan[ent] = len(rows)
            rows_out.append([label(ent).capitalize(), len(rows), sum(1 for r in rows if norm_name(r.get("name")) in names), len(there)])
            src_node = None
            for s in {r["_source"] for r in rows}:
                src_node = ctx.lineage_node("entity", "source", f"{s}:{ent}", label=f"{label(ent).capitalize()} · {s}", own=False)
                tgt_node = ctx.lineage_node("entity", ta.label, f"{tc['name']}:{ta.ENTITIES[ent][0]}", label=f"{ta.ENTITIES[ent][0]} · {tc['name']}", own=False)
                ctx.lineage_edge(src_node, tgt_node, "feeds", {"migration": ctx.id, "records": len(rows)})
        keep(ctx, "found", found)
        ctx.put("migrate", {"target": tc["id"], "entities": list(found), "sources": [list(s) for s in srcs]})
        return {"summary": f"{sum(plan.values())} record(s) to consider from {len(srcs)} source(s) into {tc['name']} ({ta.label}) — read-only.",
                "counts": {"records": sum(plan.values()), "entities": len(plan)},
                "data": {"columns": ["What", "In the sources", "Already in the target by name", f"In {tc['name']} now"], "rows": rows_out}}

    def decide(ctx):
        found = kept(ctx, "found") or {}
        have = {r["id"]: r for r in ctx.records(ctx.step_id)}
        mg = ctx.get("migrate") or {}
        tc = ctx.connection(mg["target"])
        recs = []
        for ent, rows in found.items():
            there = read_csv(ctx.dir / "data" / f"tgt-before-{ent}.csv")
            tnames = {norm_name(r.get("name")): r for r in there}
            special = set()
            for g in dupes(rows):
                g = sorted(g, key=lambda r: (str(r.get("created") or ""), str(r.get("key"))))
                for o in g[1:]:
                    special.add(o["ref"])
                    recs.append({"id": o["ref"], "entity": ent, "record": o.get("name"), "decision": "merge", "into": g[0]["ref"], "reason": f"duplicate of {g[0].get('name')} ({g[0].get('key')})"})
            for r in rows:
                if r["ref"] in special:
                    continue
                st = str(r.get("status") or "").lower()
                if st in ("blocked", "inactive", "terminated", "disabled"):
                    special.add(r["ref"])
                    recs.append({"id": r["ref"], "entity": ent, "record": r.get("name"), "decision": "retire", "into": "", "reason": f"{st} in the source"})
                elif norm_name(r.get("name")) in tnames:
                    t = tnames[norm_name(r.get("name"))]
                    special.add(r["ref"])
                    recs.append({"id": r["ref"], "entity": ent, "record": r.get("name"), "decision": "merge", "into": f"target:{t.get('key')}", "reason": f"already in {tc['name']} as {t.get('key')}"})
            rest = [r for r in rows if r["ref"] not in special]
            recs.append({"id": f"rest:{ent}", "entity": ent, "record": f"The other {len(rest)} {label(ent)}", "decision": "keep", "into": "", "reason": "active, no duplicate, not in the target yet", "count": len(rest)})
        recs = [{**r, **({k: have[r["id"]][k] for k in ("decision",) if k in have[r["id"]]} if r["id"] in have else {})} for r in recs]
        n = {d: sum(r.get("count", 1) for r in recs if r["decision"] == d) for d in ("keep", "merge", "retire")}
        return {"summary": f"Keep {n['keep']}, merge {n['merge']}, retire {n['retire']} — rules first: duplicates merge into the older record, blocked records retire, what the target already holds is not loaded again.",
                "records": recs, "counts": n, "items": [f"{r['record']}: {r['decision']} — {r['reason']}" for r in recs if not r["id"].startswith("rest:")][:8],
                "data": {"columns": ["What", "Record", "Decision", "Into", "Why"], "rows": [[label(r["entity"]), r["record"], r["decision"], r.get("into") or "", r["reason"]] for r in recs]}}

    def convert(ctx):
        found = kept(ctx, "found") or {}
        mg = ctx.get("migrate") or {}
        tc = ctx.connection(mg["target"])
        ta = adapter_of(tc)
        dec = {r["id"]: r for r in ctx.records("decide")}
        load, cross, kept_src, converted = {}, [], {}, {}
        for ent, rows in found.items():
            rest = dec.get(f"rest:{ent}", {}).get("decision", "keep")
            for r in rows:
                d = dec.get(r["ref"])
                decision = d["decision"] if d else rest
                if decision == "keep":
                    base = {k: r.get(k) for k in ENTITY[ent][1] if k not in ("key",)} | {"ref": r["ref"]}
                    prepped = ta.prepare(tc, ent, dict(base))
                    for k in prepped:
                        if prepped.get(k) != base.get(k):
                            converted.setdefault(ent, {})[k] = str(prepped.get(k))
                    load.setdefault(ent, []).append(prepped)
                    kept_src.setdefault(ent, []).append(r)
                cross.append({"source": r["_source"], "what": label(ent), "source_key": r.get("key"), "name": r.get("name"), "decision": decision,
                              "into": (d or {}).get("into") or ("(loaded)" if decision == "keep" else "")})
        for ent, recs in load.items():
            for r in recs:
                r["status"] = None
            snap(ctx, f"kept-{ent}", [{"ref": r["ref"], **{k: r.get(k) for k in ENTITY[ent][1] if k != "key"}} for r in kept_src[ent]], ["ref"] + [k for k in ENTITY[ent][1] if k != "key"])
            snap(ctx, f"load-{ent}", recs, ["ref"] + [k for k in ENTITY[ent][1] if k != "key"])
            ctx.output(f"load-{ent}.json", json.dumps([{"ref": r["ref"], "body": ta.payload(ent, r)} for r in recs], indent=1, default=str), label=f"{label(ent).capitalize()} load for {ta.label} (JSON)")
        keep(ctx, "load", load)
        keep(ctx, "converted", converted)
        ctx.output("crosswalk.csv", _csv(cross), label="Crosswalk: every source record and what happened to it (CSV)")
        return {"summary": f"{sum(len(v) for v in load.values())} record(s) converted to {ta.label} bodies; the crosswalk accounts for all {len(cross)} source record(s).",
                "counts": {"to load": sum(len(v) for v in load.values()), "source records": len(cross)},
                "data": {"columns": ["What", "To load", "Merged", "Retired"], "rows": [[label(e), len(load.get(e, [])), sum(1 for x in cross if x["what"] == label(e) and x["decision"] == "merge"),
                                                                                       sum(1 for x in cross if x["what"] == label(e) and x["decision"] == "retire")] for e in found]}}

    def prove(ctx):
        found = kept(ctx, "found") or {}
        load = kept(ctx, "load") or {}
        mg = ctx.get("migrate") or {}
        ta = adapter_of(ctx.connection(mg["target"]))
        checks = []
        cross = ctx.dir / "outputs" / "crosswalk.csv"
        accounted = [f"{slug(r['source'])}:{r['source_key']}" for r in read_csv(cross)] if cross.exists() else []
        checks.append(ctx.proof("references_real", label="Every source record is accounted for (loaded, merged or retired)", refs=[r["ref"] for rows in found.values() for r in rows], known=accounted))
        converted = kept(ctx, "converted") or {}
        for ent, recs in load.items():
            K, L = {"source": "file", "file": f"kept-{ent}.csv"}, {"source": "file", "file": f"load-{ent}.csv"}
            conv = converted.get(ent) or {}
            cols = [k for k in ENTITY[ent][1] if k not in COMPARE_SKIP and k not in conv and any(r.get(k) not in (None, "") for r in recs)]
            if conv:
                checks.append({"name": f"converted:{ent}", "label": f"{label(ent).capitalize()}: converted by the target's rules", "status": "pass",
                               "detail": "; ".join(f"{k} → {v} (the connection's setting for {ta.label})" for k, v in conv.items()), "measured": len(conv), "expected": "listed, not compared"})
            checks.append(ctx.proof("row_count", label=f"{label(ent).capitalize()}: kept in the source vs in the load", source=K, target=L))
            checks.append(ctx.proof("checksum", label=f"{label(ent).capitalize()}: fingerprints of {', '.join(cols[:5])}", source=K, target=L, columns=cols))
            m = spec.measures.get(ent)
            if m and any(r.get(m[0]) not in (None, "") for r in recs):
                checks.append(ctx.proof("totals", label=f"{label(ent).capitalize()}: {m[0].replace('_', ' ')} by {m[1]} (control totals)", source=K, target=L, measures=[m[0]], by=m[1], tolerance_pct=0.0))
            checks.append(ctx.proof("sample_diff", label=f"{label(ent).capitalize()}: every record field by field", source=K, target=L, keys=["ref"], n=1000, columns=cols))
            before = read_csv(ctx.dir / "data" / f"tgt-before-{ent}.csv")
            names = {norm_name(r.get("name")) for r in before}
            tc = ctx.connection(mg["target"])
            tests = []
            for r in recs:
                probs = value_problems(ent, r) + ta.problems(tc, ent, r) + (["already in the target"] if norm_name(r.get("name")) in names else [])
                tests.append({"name": r["ref"], "status": "fail" if probs else "pass", "detail": "; ".join(probs) or "passes"})
            checks.append(ctx.proof("tests_run", label=f"{label(ent).capitalize()}: each record against {ta.label}'s rules (dry run)", results=tests))
        bad = sum(1 for c in checks if c["status"] == "fail")
        return {"summary": f"{len(checks)} proof(s) of the conversion, old and new side by side: {len(checks) - bad} pass, {bad} fail.", "data": {"checks": checks},
                "counts": {"pass": len(checks) - bad, "fail": bad}}

    def handover(ctx):
        load = kept(ctx, "load") or {}
        mg = ctx.get("migrate") or {}
        tc = ctx.connection(mg["target"])
        approver = db.user(ctx.st.get("approver") or "") or {}
        return {"summary": f"Sign-off: load {sum(len(v) for v in load.values())} record(s) into {tc['name']}, with the crosswalk and the proofs as the evidence pack.",
                "data": {"items": [{"title": f"{label(e).capitalize()}", "detail": f"{len(v)} record(s) into {adapter_of(tc).ENTITIES[e][0]}"} for e, v in load.items()]
                         + [{"title": "Evidence", "detail": "crosswalk.csv, the load files and every proof — in the evidence pack"},
                            {"title": "Then", "detail": "The load is one write a named person approves in the Validation queue; Relay reads the target back and reconciles every record."},
                            {"title": "Owner sign-off", "detail": approver.get("name") or "the owner of this work item"}]}}

    def run(ctx):
        load = kept(ctx, "load") or {}
        mg = ctx.get("migrate") or {}
        tc = ctx.connection(mg["target"])
        ta = adapter_of(tc)
        ops = [{"op": "create", "entity": ent, "ref": r["ref"], "data": ta.payload(ent, r)} for ent, recs in load.items() for r in recs]
        if not ops:
            return {"summary": "Nothing to load: every record was merged or retired.", "data": {"checks": [{"name": "write", "label": "No load was requested", "status": "skip", "detail": "every record was merged or retired"}]}}
        keep(ctx, f"load-{ctx.step_id}", {"conn": tc["id"], "entities": load})
        cp = request_write(ctx, tc, "migration load", ops, f"Load {len(ops)} record(s) into {tc['name']}", [f"{label(e).capitalize()}: {len(v)}" for e, v in load.items()])
        return {"summary": f"The load ({len(ops)} record(s)) waits for its approval in the Validation queue; once written, Relay reads {tc['name']} back and reconciles every record.",
                "counts": {"to load": len(ops)}, "data": {"checks": [pending(cp, tc, len(ops))]}}

    return wb.Work(title=title, needs_source=True, fields=[
        wb.Field("target", "Move into", "select", options=_target_options(kinds), required=True, help="A connection whose scope allows writes with approval; the item's own connections are the sources."),
        wb.Field("entities", "What to move", "text", help=f"Blank: everything both sides hold ({', '.join(label(e) for e in spec.entities[:4])} …).")], steps={
        "Discover": wb.Step(kind="platform", run=discover, agent="Scanner", text="Every record in the sources and what the target already holds — read-only"),
        "Decide": wb.Step(kind="deterministic", run=decide, agent="Decider", edit=wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("keep", "Keep"), ("merge", "Merge"), ("retire", "Retire"))),
                                                                                      wb.Column("record", "Record", readonly=True), wb.Column("reason", "Why", readonly=True)], add=False, remove=False, label="decision"),
                          text="Keep, merge or retire with the reason — duplicates merge into the older record, blocked ones retire, what the target holds is not loaded twice"),
        "Convert": wb.Step(kind="deterministic", run=convert, agent="Converter", text="The kept records as the target's own bodies, and a crosswalk for every source record — rules first"),
        "Prove": wb.Step(kind="proof", run=prove, view="gates", agent="Prover", back_to="decide", text="Old and new side by side: counts, fingerprints, control totals and every record field by field, and a dry run against the target's rules"),
        "Hand over": wb.Step(kind="person", run=handover, view="plan", approver=True, back_to="decide", text="The owner signs off the load and its evidence pack (a send back returns to Decide)"),
        "Run": wb.Step(kind="platform", run=run, view="gates", agent="Loader", text="The load is one write a named person approves; then Relay reads the target back and reconciles record by record",
                       actions={"verify": wb.Action(label="Read back and reconcile", kind="platform", run=verify_fn(spec), agent="Reconciler", help="Reads the target again and compares every loaded record.")}),
    })


# ================================================================== Run & support

def run_work(spec: Spec, title: str) -> wb.Work:
    @stepfn
    def watch(ctx):
        checks, breaks = [], []
        for c, a in systems(ctx):
            runs = ctx.seen.runs(c, a) if type(a).runs is not SysAdapter.runs else []
            by: dict[str, list] = {}
            for r in runs:
                by.setdefault(r["job"], []).append(r)
            for job, rs in by.items():
                rs.sort(key=lambda x: x.get("started") or 0, reverse=True)
                last = rs[0]
                streak = 0
                for r in rs:
                    if r["status"] in ("failed", "warning"):
                        streak += 1
                    else:
                        break
                st = "pass" if last["status"] in ("succeeded", "running", "queued") else "fail" if last["status"] == "failed" else "warn"
                checks.append({"name": f"{c['id']}:{job}", "label": f"{last.get('label') or job} · {c['name']}", "status": st, "measured": last["status"], "expected": "succeeded",
                               "detail": f"last run {stamp(last.get('started'))}" + (f"; failing {streak} run(s) in a row: {(last.get('error') or '')[:200]}" if streak else "")})
                if st != "pass":
                    breaks.append({"conn": c["id"], "system": c["name"], "job": job, "label": last.get("label") or job, "status": last["status"], "streak": streak, "error": last.get("error") or "",
                                   "since": rs[streak - 1].get("started") if streak else last.get("started"), "run": last.get("id") or ""})
        for mon in spec.monitors:
            for g in mon(ctx, ctx.seen) or []:
                checks.append({k: v for k, v in g.items() if k != "break"})
                if g.get("break"):
                    breaks.append(g["break"])
        ctx.put("breaks", breaks)
        eid = ctx.evidence("What was watched", {"checks": checks}, kind="watch", ok=not breaks)
        for x in checks:
            x.setdefault("evidence", eid)
        return {"summary": f"{len(checks)} job(s) and check(s) watched on {len(systems(ctx))} system(s): {len(breaks)} need attention.", "counts": {"watched": len(checks), "breaks": len(breaks)},
                "data": {"checks": checks}}

    def alert(ctx):
        brks = ctx.get("breaks") or []
        if not brks:
            return {"summary": "Everything ran: nothing to alert.", "next": "report", "counts": {"breaks": 0}}
        rules = learned(spec.module)
        for b in brks:
            rule = next((r for r in rules if re.search(r["signature"], b.get("error") or "", re.I)), None)
            sig = next((s for s in spec.signatures if s.match(b.get("error") or "")), None)
            b["cause"] = (rule or {}).get("cause") or (sig.cause if sig else b.get("cause") or "not a known error — a person diagnoses it")
            b["fix"] = (rule or {}).get("fix") or (sig.fix if sig else b.get("fix") or "")
            b["route"] = b.get("route") or ("change" if rule else sig.route if sig else "ticket")
            b["id"] = f"b-{slug(b['system'])}-{slug(b['job'])}"
        ctx.put("breaks", brks)
        return {"summary": f"{len(brks)} break(s), one alert each with its likely cause — not one per failed run.", "counts": {"breaks": len(brks)},
                "items": [f"{b['label']} ({b['system']}): {b['cause']}"[:240] for b in brks[:6]],
                "data": {"columns": ["System", "What", "Failing runs", "Since", "Likely cause"], "rows": [[b["system"], b["label"], b.get("streak") or 1, stamp(b.get("since")), b["cause"]] for b in brks]}}

    def fix(ctx):
        have = {r["id"]: r for r in ctx.records(ctx.step_id)}
        recs = [{**b, **({k: have[b["id"]][k] for k in ("route", "note") if k in have[b["id"]]} if b["id"] in have else {})} for b in ctx.get("breaks") or []]
        for r in recs:
            r.setdefault("note", "")
        return {"summary": f"{len(recs)} break(s): choose who fixes each — a Change work item here, Self-healing, a ticket, or expected. Nothing goes out until you confirm.",
                "records": recs, "counts": {"changes": sum(1 for r in recs if r["route"] == "change"), "tickets": sum(1 for r in recs if r["route"] == "ticket")},
                "data": {"columns": ["System", "What", "Proposed route", "Likely cause"], "rows": [[r["system"], r["label"], r["route"], r["cause"]] for r in recs]}}

    def approve(ctx):
        rows, done = [], []
        for b in ctx.records("fix"):
            title = f"{b['label']} fails on {b['system']}"
            body = f"{b.get('error') or b.get('what') or ''}\n\nLikely cause: {b['cause']}\nFix: {b.get('fix') or '—'}\n" + (f"Note: {b['note']}\n" if b.get("note") else "") + f"Work item: {wb.route_of(ctx.st)}"
            if b["route"] == "change":
                it = wb.create(spec.module, "change", f"Fix: {b['label']}"[:150], who=ctx.owner, brief=f"{b['job']} fails on {b['system']}: {b.get('error') or ''}\n\n{b.get('note') or ''}",
                               connections=[b["conn"]] if b.get("conn") else [], scope={}, approver=ctx.st.get("approver"),
                               visibility=(db.project(ctx.id) or {}).get("visibility") or "private", team_id=(db.project(ctx.id) or {}).get("team_id"), parent=ctx.id)
                h = ctx._handoff({"kind": "change", "label": title, "status": "Change work item opened", "link": wb.route_of(it), "item": it["id"]})
            elif b["route"] == "heal":
                h = ctx.heal(title, body, place=f"{b['system']} ({registry.BY_ID[spec.module]['short']})", signature=f"{spec.module}:{slug(b['job'])}", subject={"system": b["system"], "job": b["job"]})
            elif b["route"] == "ticket":
                h = ctx.ticket(title, body, priority="P2" if (b.get("streak") or 0) >= 2 else "P3", about=b["label"])
            else:
                h = {"kind": b["route"], "label": title, "status": "expected — recorded" if b["route"] == "expected" else "ignored this time"}
            done.append(h)
            rows.append([b["system"], b["label"], {"change": "Change", "heal": "Self-healing", "ticket": "Ticket", "expected": "Expected", "ignore": "Ignored"}[b["route"]], h.get("status"),
                         h.get("item") or h.get("case") or h.get("checkpoint") or h.get("output") or ""])
        return {"summary": f"{sum(1 for h in done if h['kind'] == 'change')} Change item(s), {sum(1 for h in done if h['kind'] == 'heal')} to Self-healing, {sum(1 for h in done if h['kind'] == 'ticket')} ticket(s) — as you approved.",
                "data": {"columns": ["System", "What", "Route", "Status", "Reference"], "rows": rows}, "counts": {"hand-offs": len(done)}}

    def report(ctx):
        rounds = (ctx.st.get("rounds") or [])[-11:]
        hist = []
        for r in rounds:
            w = next((s for s in r["steps"] if s["id"] == "watch"), {})
            c = w.get("counts") or {}
            hist.append([time.strftime("%d %b %H:%M", time.gmtime(r["ended"])), c.get("watched"), c.get("breaks")])
        brks = ctx.get("breaks") or []
        hist.append([time.strftime("%d %b %H:%M", time.gmtime()), len((ctx.result("watch") or {}).get("data", {}).get("checks") or []), len(brks)])
        text = f"# {spec.noun} run report: {ctx.title}\n\n{time.strftime('%d %B %Y %H:%M UTC', time.gmtime())}\n\n" + "".join(f"- {b['system']} · {b['label']}: {b['cause']} → {b.get('route')}\n" for b in ctx.records("fix") or brks) \
               + "\n## Recent rounds\n\n" + "".join(f"- {h[0]}: {h[1]} watched, {h[2]} break(s)\n" for h in hist)
        ctx.output(f"report-{time.strftime('%Y%m%d-%H%M', time.gmtime())}.md", text, label="Run report (Markdown)")
        return {"summary": f"{len(brks)} break(s) this round" + (", each routed as you approved." if brks else "; everything ran."), "counts": {"breaks": len(brks)},
                "data": {"columns": ["Round", "Watched", "Breaks"], "rows": hist}}

    return wb.Work(title=title, needs_source=True, schedule_from="Watch", fields=[wb.Field("schedule", "Watch it", "cadence", default={"every": "day", "at": "06:00", "tz": "UTC"})], steps={
        "Watch": wb.Step(kind="proof", run=watch, view="gates", agent="Watcher", text=f"Every scheduled job, script and integration on the {spec.noun} — its last runs and the vendor's own error text, read-only"),
        "Alert": wb.Step(kind="deterministic", run=alert, agent="Triage", text="One alert per broken job with its likely cause — from the vendor's error text and the fixes Relay learned"),
        "Fix": wb.Step(kind="deterministic", run=fix, agent="Triage", edit=wb.Edit(columns=[wb.Column("route", "Route", "select", options=(("change", "Open a Change work item"), ("heal", "Self-healing"), ("ticket", "Raise a ticket"),
                                                                                                                                         ("expected", "Expected — no action"), ("ignore", "Ignore this time"))),
                                                                                      wb.Column("note", "Note for whoever fixes it", "longtext"), wb.Column("system", "System", readonly=True), wb.Column("label", "What", readonly=True)],
                                                                             add=False, remove=False, label="break"),
                       text="Relay proposes who fixes each break and you confirm or change it"),
        "Approve": wb.Step(kind="platform", run=approve, agent="Dispatcher", text="The approved hand-offs go out: a Change work item (diagnosis → fix → approval), Self-healing, or a ticket through the service desk's own approval"),
        "Report": wb.Step(kind="deterministic", run=report, agent="Reporter", confirm_if=lambda ctx, out: bool(ctx.get("breaks")), text="A service report of the round against the last ones; you confirm it when there were breaks"),
    })
