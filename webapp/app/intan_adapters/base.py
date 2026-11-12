"""What every Integration analytics discovery adapter shares (build-plan v2, P13).

An adapter is one module with:
  KIND, LABEL, GROUP, DOCS           what it reads and the vendor API it follows
  AUTH                               how it signs in, in words ("service account", "API key", ...)
  CONFIG = [{name, label, hint, required}]   settings kept in the open (URL, folder, account id)
  SECRETS = [{name, label}]          credentials, stored by name in the secrets store, never shown back
  discover(cfg, secrets, client) -> {"systems": [...], "integrations": [...], "runs": [...], "credentials": [...], "signals": [...]}

Record shapes (everything optional except the ids and names):
  integration  {ext_id, name, kind, via, from_system, to_system, schedule, owner, properties, depends_on: [ext_id],
                reads: ["<warehouse>:<object>"], writes: ["<warehouse>:<object>"], feeds: ["report name"]}
               kind: Flow - Pipeline - Integration - Bot - Package - API - API pull - API push - File - Webhook - Connector - Refresh
  run          {integration: ext_id, ext_id, started, ended, status: success|failed|skipped|running, duration_s, volume, error}
  credential   {name, kind, integration: ext_id | None, expires: epoch | None, status}
  signal       {kind: usage|schema_change|screen_change|licence, integration: ext_id | None, text, value, limit, due: epoch | None}
  system       {name, kind}

Adapters are read-only: they only ever GET (or POST a query, where the vendor's API is query-by-POST). The shared
client retries a 429 with the vendor's Retry-After, turns a 401 / 403 into AuthError ("sign in again"), gives up on
a 5xx after a few tries, and never puts a header or a secret into an error message.
"""
from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


class AuthError(Exception):
    """The source refused the credential (401 / 403): renew it and scan again."""


class SourceError(Exception):
    """The source could not be read (5xx after retries, unreachable, malformed)."""


class Client:
    def __init__(self, base: str, headers: dict | None = None, *, timeout: float = 12.0, retries: int = 3, sleep=time.sleep):
        self.base = (base or "").rstrip("/")
        self.headers = {"Accept": "application/json", **(headers or {})}
        self.timeout, self.retries, self._sleep = timeout, retries, sleep
        self.calls = 0

    @staticmethod
    def basic(user: str, password: str) -> dict:
        return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}

    @staticmethod
    def bearer(token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    def url(self, path: str, params: dict | None = None) -> str:
        u = self.base if not path else path if path.startswith("http") else self.base + ("/" if not path.startswith("/") else "") + path
        if params:
            u += ("&" if "?" in u else "?") + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        return u

    def request(self, method: str, path: str, params: dict | None = None, body: dict | None = None, headers: dict | None = None):
        url = self.url(path, params)
        data = json.dumps(body).encode() if body is not None else None
        hdrs = {**self.headers, **(headers or {})}
        if data is not None:
            hdrs.setdefault("Content-Type", "application/json")
        last = None
        for attempt in range(self.retries + 1):
            self.calls += 1
            req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    raw = r.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                code = e.code
                if code in (401, 403):
                    raise AuthError(f"The source refused the sign-in ({code}). Renew the credential and scan again.") from None
                if code == 429:
                    wait = e.headers.get("Retry-After")
                    self._sleep(min(2.0, float(wait)) if wait and re.match(r"^\d+(\.\d+)?$", wait) else 0.5 * (attempt + 1))
                    last = f"rate limited (429)"
                    continue
                if code >= 500:
                    last = f"server error ({code})"
                    self._sleep(0.2 * (attempt + 1))
                    continue
                raise SourceError(f"The source answered {code} for {urllib.parse.urlparse(url).path}.") from None
            except urllib.error.URLError as e:
                last = f"unreachable ({getattr(e, 'reason', e)})"
                self._sleep(0.2 * (attempt + 1))
                continue
            except (ValueError, json.JSONDecodeError):
                raise SourceError("The source did not answer with JSON.") from None
        raise SourceError(f"The source kept failing: {last}. Try again later.")

    def get(self, path: str, params: dict | None = None, headers: dict | None = None):
        return self.request("GET", path, params=params, headers=headers)

    def post(self, path: str, body: dict | None = None, params: dict | None = None, headers: dict | None = None):
        return self.request("POST", path, params=params, body=body or {}, headers=headers)


def ts(value) -> float | None:
    """An ISO 8601 / epoch / .NET-style timestamp as epoch seconds (None when absent)."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value) / (1000 if value > 1e11 else 1)
    s = str(value).strip()
    m = re.match(r"^/Date\((\d+)\)/$", s)                       # OData v2 (SAP CPI)
    if m:
        return int(m.group(1)) / 1000
    if re.match(r"^\d{10}(\.\d+)?$", s):
        return float(s)
    if re.match(r"^\d{13}$", s):
        return int(s) / 1000
    s = s.replace("Z", "+00:00")
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)                       # more than microseconds
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d"):
            try:
                d = datetime.strptime(s[:19], fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def arrow(text: str) -> tuple[str | None, str | None]:
    """'SAP -> Salesforce' or 'SAP -> Salesforce' in a name or description -> (from, to)."""
    m = re.search(r"([A-Za-z0-9 ./&+-]+?)(?:\s*(?:→|->|=>)\s*|\s+to\s+)([A-Za-z0-9 ./&+-]+)", text or "")
    if not m:
        return None, None
    return m.group(1).strip(), m.group(2).strip()


def expires_from(texts) -> float | None:
    """'expires:2026-11-08' / 'expires=2026-11-08' in annotations, tags or descriptions."""
    for t in texts or []:
        m = re.search(r"expir(?:es|y)\s*[:=]\s*(\d{4}-\d{2}-\d{2}(?:T[\d:]+)?)", str(t), re.I)
        if m:
            return ts(m.group(1))
    return None


def owner_from(texts) -> str | None:
    for t in texts or []:
        m = re.search(r"owner\s*[:=]\s*([^,;|]+)", str(t), re.I)
        if m:
            return m.group(1).strip()
    return None


def writes_from(texts) -> list[str]:
    """'writes: snowflake:FINANCE.AP_INVOICES, snowflake:FINANCE.AP_LINES' in a description -> warehouse objects."""
    out = []
    for t in texts or []:
        m = re.search(r"writes\s*[:=]\s*([^;|\n]+)", str(t), re.I)
        if m:
            out += [x.strip() for x in m.group(1).split(",") if ":" in x]
    return out


def empty() -> dict:
    return {"systems": [], "integrations": [], "runs": [], "credentials": [], "signals": []}


def schedule_text(every_min: int | None = None, cron: str | None = None, text: str | None = None) -> str:
    if text:
        return text
    if every_min:
        return f"Every {every_min} min" if every_min < 60 else ("Hourly" if every_min == 60 else f"Every {every_min // 60} h" if every_min % 60 == 0 else f"Every {every_min} min")
    if cron:
        c = re.sub(r"\s+", " ", cron.replace("?", "*").strip())
        m = re.match(r"^(\d+) (\d+) \* \* \*$", c)
        if m:
            return f"Daily {int(m.group(2)):02d}:{int(m.group(1)):02d}"
        m = re.match(r"^\*/(\d+) \*", c)
        if m:
            return f"Every {m.group(1)} min"
        m = re.match(r"^(\d+) \* \* \* \*$", c)
        if m:
            return "Hourly" if int(m.group(1)) == 0 else f"Hourly at :{int(m.group(1)):02d}"
        m = re.match(r"^(\d+) \*/(\d+) \* \* \*$", c)
        if m:
            return f"Every {m.group(2)} h"
        return cron
    return "Unknown"
