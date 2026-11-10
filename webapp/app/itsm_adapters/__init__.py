"""ITSM adapters (build-plan v2, P12): one small client per service desk, following the vendor's public REST API.

Shared here: the HTTP call with the behaviour every adapter needs - pagination is the adapter's, but rate limits
(429 + Retry-After) back off and retry, server errors (5xx) retry with a short back-off, expired or wrong
credentials (401) become SignInAgain so the source shows "sign in again", and a 403 says the service account lacks
access. Every adapter returns tickets in one normalised shape (`normalise`), so the triage never sees vendor fields.

Reads are the default. Writes (comment / note, priority, labels / tags, transitions) exist on the adapters but the
app only calls them through `itsm.write_back(...)`, which refuses without an accepted checkpoint.
"""
from __future__ import annotations

import os
import time

import httpx

RETRY_CAP_S = float(os.environ.get("ITSM_RETRY_CAP_S", "30"))       # the most we wait on one Retry-After
TIMEOUT_S = float(os.environ.get("ITSM_HTTP_TIMEOUT_S", "25"))
ATTEMPTS = int(os.environ.get("ITSM_HTTP_ATTEMPTS", "4"))


class AdapterError(Exception):
    """Something the person must read: the vendor refused, the object is gone, the request was wrong."""


class SignInAgain(AdapterError):
    """401: the service account's credential has expired or is wrong - the source needs a new token."""


class NoAccess(AdapterError):
    """403: the service account cannot see or change this object."""


class NotFound(AdapterError):
    """404: the ticket, project or group does not exist (any more)."""


class Unavailable(AdapterError):
    """The service kept failing (429 or 5xx) after the retries; try again later."""


class Client:
    """One service desk's HTTP session with the retry rules above. Subclasses set `auth` (a httpx auth tuple or a
    bearer header) and build their own endpoints."""

    label = "service desk"

    def __init__(self, base_url: str, auth: tuple[str, str] | None = None, bearer: str | None = None, attempts: int = ATTEMPTS):
        self.base = base_url.rstrip("/")
        self.auth = auth
        self.headers = {"Accept": "application/json"}
        if bearer:
            self.headers["Authorization"] = f"Bearer {bearer}"
        self.attempts = max(1, attempts)
        self.calls = 0            # for tests and the source status: how many HTTP calls, how many retries
        self.retries = 0
        self.sleep = time.sleep   # swapped in tests

    def request(self, method: str, path: str, *, params: dict | None = None, json: dict | list | None = None, ok=(200, 201, 204)) -> httpx.Response:
        url = path if path.startswith("http") else self.base + path
        last: str = ""
        for attempt in range(self.attempts):
            self.calls += 1
            try:
                with httpx.Client(timeout=TIMEOUT_S, auth=self.auth, headers=self.headers) as c:
                    r = c.request(method, url, params=params, json=json)
            except httpx.TransportError as e:
                last = f"{self.label} could not be reached ({e.__class__.__name__})."
                self.retries += 1
                self.sleep(min(RETRY_CAP_S, 0.5 * 2 ** attempt))
                continue
            if r.status_code == 401:
                raise SignInAgain(f"{self.label} rejected the service account's credential: sign in again with a new token.")
            if r.status_code == 403:
                raise NoAccess(f"{self.label}: the service account has no access to {path.split('?')[0]}.")
            if r.status_code == 404:
                raise NotFound(f"{self.label}: {path.split('?')[0]} was not found.")
            if r.status_code == 429:
                wait = _retry_after(r)
                last = f"{self.label} rate limit reached; waited {wait:.0f} s."
                self.retries += 1
                self.sleep(wait)
                continue
            if r.status_code >= 500:
                last = f"{self.label} server error {r.status_code}: {_message(r)}"
                self.retries += 1
                self.sleep(min(RETRY_CAP_S, 0.5 * 2 ** attempt))
                continue
            if r.status_code not in ok:
                raise AdapterError(f"{self.label} refused {method} {path.split('?')[0]} ({r.status_code}): {_message(r)}")
            return r
        raise Unavailable(last or f"{self.label} did not answer after {self.attempts} attempts.")

    def get(self, path: str, **kw) -> httpx.Response:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw) -> httpx.Response:
        return self.request("POST", path, **kw)

    def put(self, path: str, **kw) -> httpx.Response:
        return self.request("PUT", path, **kw)


def _retry_after(r: httpx.Response) -> float:
    try:
        return max(0.0, min(RETRY_CAP_S, float(r.headers.get("Retry-After") or r.headers.get("X-RateLimit-Reset") or 2)))
    except ValueError:
        return min(RETRY_CAP_S, 2.0)


def _message(r: httpx.Response) -> str:
    try:
        j = r.json()
    except ValueError:
        return (r.text or "")[:200]
    if isinstance(j, dict):
        msgs = j.get("errorMessages") or j.get("message") or j.get("description") or j.get("errors")
        if isinstance(msgs, list):
            return "; ".join(str(m) if not isinstance(m, dict) else f"{m.get('field')}: {m.get('message')}" for m in msgs)[:300]
        if msgs:
            return str(msgs)[:300]
    return str(j)[:200]


def normalise(kind: str, key: str, vendor_id: str, title: str, description: str, status: str, is_open: bool, priority: str,
              reporter: str, reporter_email: str, team: str, created: float, updated: float, due: float | None, labels: list[str],
              url: str, raw: dict) -> dict:
    return {"kind": kind, "key": key, "vendor_id": str(vendor_id), "title": (title or "").strip()[:400], "description": (description or "").strip()[:4000],
            "status": status, "open": bool(is_open), "priority": priority or "", "reporter": reporter or "", "reporter_email": reporter_email or "",
            "team": team or "", "created": created, "updated": updated, "due": due, "labels": [str(x) for x in (labels or [])][:30], "url": url, "raw": raw}


def parse_time(s: str | None) -> float | None:
    """ISO 8601 as the vendors write it (Jira: 2026-11-05T09:12:33.000+0000; Freshservice: 2026-11-05T09:12:33Z) -> epoch."""
    if not s:
        return None
    from datetime import datetime, timezone
    txt = str(s).strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    if len(txt) >= 5 and txt[-5] in "+-" and txt[-3] != ":":
        txt = txt[:-2] + ":" + txt[-2:]                 # +0000 -> +00:00
    try:
        d = datetime.fromisoformat(txt)
    except ValueError:
        try:
            d = datetime.strptime(txt[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()
