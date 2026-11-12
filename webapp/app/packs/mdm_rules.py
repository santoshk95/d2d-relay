"""Master data - the rules (no agent): the Reltio adapter, reading masters (Reltio entities, spreadsheet and CSV masters)
into one neutral record, the match rules with the false-friend guard, survivorship, and the gaps a golden record must
not have. The mock lab's Reltio simulator and the supplier master workbook stand in (tests/mocklab/sims/mdm.py, excel.py).

A record: {id, source, type (customer|supplier|product), name, code, country, city, tax_id, email, segment, sources
[crosswalks], created, entity (the Reltio id, if any)}.
"""
from __future__ import annotations

import csv
import difflib
import io
import re
from collections import Counter, defaultdict
from pathlib import Path

from .. import connectors
from . import _w1
from ._w1 import Kind, cfg, secret

OT = "configuration/entityTypes/Organization"
PT = "configuration/entityTypes/Product"
FIELDS = ("name", "code", "country", "city", "tax_id", "email", "segment")
LEGAL = re.compile(r"\b(ltd|limited|pvt|private|plc|llp|llc|inc|incorporated|gmbh|corp|corporation|co|company)\b\.?", re.I)
DEFAULT_RULES = [
    {"id": "r-taxid", "name": "Same tax id", "attributes": "tax_id", "compare": "exact", "threshold": 1.0, "action": "merge", "score": 97, "enabled": True},
    {"id": "r-name-country", "name": "Same name, same country", "attributes": "name, country", "compare": "normalised", "threshold": 1.0, "action": "suggest", "score": 90, "enabled": True},
    {"id": "r-similar", "name": "Similar name, same city or email", "attributes": "name, city|email", "compare": "similar", "threshold": 0.88, "action": "suggest", "score": 80, "enabled": True},
]
HEADERS = {"name": ("name", "supplier name", "customer name", "legal name", "company", "product name"), "code": ("code", "supplier code", "customer code", "vendor code", "sku", "id", "number"),
           "country": ("country", "country code"), "city": ("city", "town"), "tax_id": ("gstin", "tax id", "taxid", "vat", "vat number", "tax number"), "email": ("email", "e-mail", "email address"),
           "segment": ("segment", "category", "type"), "terms": ("payment terms", "payment terms days", "terms")}


def norm(name: str) -> str:
    s = (name or "").lower().replace("&", " and ")
    s = LEGAL.sub(" ", s)
    s = re.sub(r"\band\b", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def similar(a: str, b: str) -> float:
    """How alike two names are (0 ... 1); names that differ in a number (Store 13, Store 14) are two organisations."""
    if set(re.findall(r"\d+", a or "")) != set(re.findall(r"\d+", b or "")):
        return 0.0
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def domain(email: str | None) -> str:
    return (email or "").split("@")[-1].lower() if email and "@" in email else ""


# ================================================================== Reltio

class Reltio(Kind):
    """Reltio Connected Data Platform - the tenant REST API: entities (filter, select, max / offset), potential matches,
    merge (_sameAs), not a match (_notMatch), create, the activity log; OAuth 2.0 client credentials."""
    kind, label, category = "reltio", "Reltio", "mdm"
    signin = ["service_account"]
    fields = [("base_url", "Tenant API (https://<env>.reltio.com/reltio/api/<tenant>)", True), ("auth_url", "OAuth token endpoint (https://auth.reltio.com/oauth/token)", True),
              ("client_id", "Client id", True)]
    secrets = {"service_account": ["client_secret"]}
    can_write = True
    simulator = "reltio"

    def auth(self, c):
        def fetch():
            r = self.call(c, "POST", cfg(c, "auth_url"), form={"grant_type": "client_credentials"}, headers=self.basic(cfg(c, "client_id"), secret(c, "client_secret")), auth=False)
            return r["access_token"], r.get("expires_in") or 3599
        return {"Authorization": "Bearer " + self.token(c, fetch)}

    def entities(self, c, flt: str = "") -> list[dict]:
        out, off = [], 0
        while True:
            page = self.call(c, "GET", "/entities", params={**({"filter": flt} if flt else {}), "max": 200, "offset": off}) or []
            out += page
            off += len(page)
            if len(page) < 200 or len(out) > 100000:
                return out

    def matches(self, c, eid: str) -> list[dict]:
        r = self.call(c, "GET", f"/entities/{eid}/_matches") or {}
        return [{"other": x["object"]["uri"].split("/")[-1], "rule": g.split("/")[-1], "score": x.get("matchScore")} for g, xs in r.items() for x in xs]

    def activities(self, c, limit: int = 200) -> list[dict]:
        out, off = [], 0
        while len(out) < limit:
            page = self.call(c, "GET", "/activities", params={"max": 100, "offset": off}) or []
            out += page
            off += len(page)
            if len(page) < 100:
                break
        return out

    def test(self, c):
        r = self.call(c, "GET", "/entities/_total")
        return {"ok": True, "sees": f"{r.get('total', 0)} entit(ies)"}

    def list_objects(self, c, search=""):
        return [{"object": t, "type": "entity type"} for t in ("Organization", "Product") if search.lower() in t.lower()]

    def read(self, c, obj, limit=100):
        rows = [record_of(e) for e in self.entities(c, f"equals(type,'configuration/entityTypes/{obj}')")[:limit]]
        cols = ["id", "type", "name", "code", "country", "city", "tax_id", "email"]
        return {"columns": cols, "rows": [{k: r.get(k) for k in cols} for r in rows], "row_count": len(rows)}

    def _write(self, c, obj, payload, approval):
        done = []
        for op in payload.get("ops") or []:
            if op["op"] == "merge":
                self.call(c, "POST", f"/entities/{op['winner']}/_sameAs", params={"uri": f"entities/{op['loser']}"}, approval=approval)
            elif op["op"] == "not_match":
                self.call(c, "POST", f"/entities/{op['a']}/_notMatch", params={"uri": f"entities/{op['b']}"}, approval=approval)
            elif op["op"] == "create":
                res = self.call(c, "POST", "/entities", json_body=op["entities"], approval=approval) or []
                bad = [x for x in res if not x.get("successful")]
                if bad:
                    raise connectors.ConnectorError(f"Reltio refused {len(bad)} entit(ies): {(bad[0].get('errors') or {}).get('errorMessage')}")
            else:
                raise connectors.ConnectorError(f"unknown change {op['op']}")
            done.append(op.get("what") or op["op"])
        return {"ok": True, "done": done}


RELTIO = _w1.register(Reltio())


def _val(e: dict, name: str):
    v = (e.get("attributes") or {}).get(name) or []
    return v[0].get("value") if v and isinstance(v[0], dict) else None


def record_of(e: dict) -> dict:
    eid = e["uri"].split("/")[-1]
    role = (_val(e, "Role") or ("Product" if e.get("type") == PT else "Customer")).lower()
    return {"id": eid, "entity": eid, "source": "Reltio", "type": role if role in ("customer", "supplier") else "product", "name": _val(e, "Name") or e.get("label") or "",
            "code": _val(e, "CustomerCode") or _val(e, "SupplierCode") or _val(e, "SKU"), "country": _val(e, "Country"), "city": _val(e, "City"), "tax_id": _val(e, "TaxId"),
            "email": _val(e, "Email"), "segment": _val(e, "Segment") or _val(e, "Category"),
            "sources": [f"{cw['type'].split('/')[-1]}:{cw.get('value')}" for cw in e.get("crosswalks") or []], "created": e.get("createdTime")}


def from_reltio(c: dict) -> list[dict]:
    return [record_of(e) for e in RELTIO.entities(c)]


# ================================================================== spreadsheet and CSV masters

def _map(headers: list[str]) -> dict[int, str]:
    out = {}
    for i, h in enumerate(headers):
        k = re.sub(r"\s+", " ", str(h or "").strip().lower())
        for f, names in HEADERS.items():
            if k in names and f not in out.values():
                out[i] = f
                break
    return out


def _rows_to_records(name: str, sheet: str, rows: list[list], kind: str) -> list[dict]:
    if not rows:
        return []
    head = next((i for i, r in enumerate(rows[:10]) if sum(1 for v in r if isinstance(v, str) and v.strip()) >= 2), 0)
    m = _map(rows[head])
    if "name" not in m.values():
        return []
    out = []
    for n, r in enumerate(rows[head + 1:], head + 2):
        rec = {f: (str(r[i]).strip() if i < len(r) and r[i] not in (None, "") else None) for i, f in m.items()}
        if not rec.get("name"):
            continue
        rec.update(id=f"{name}!{sheet}!{n}", source=f"{name} > {sheet}", type=kind, sources=[f"{Path(name).stem}:{rec.get('code') or n}"], entity=None, row=n)
        out.append(rec)
    return out


def from_files(paths: list[Path]) -> list[dict]:
    """Masters kept in spreadsheets (.xlsx, a sheet per master with a header row) or CSV files."""
    import zipfile
    out: list[dict] = []
    blobs: list[tuple[str, bytes]] = []
    for p in paths:
        if p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as z:
                blobs += [(Path(n).name, z.read(n)) for n in z.namelist() if not n.endswith("/")]
        else:
            blobs.append((p.name, p.read_bytes()))
    for name, b in blobs:
        kind = "supplier" if re.search(r"(?i)supplier|vendor", name) else "product" if re.search(r"(?i)product|item|sku", name) else "customer"
        if name.lower().endswith((".xlsx", ".xlsm")):
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True, data_only=True)
            for ws in wb.worksheets:
                if ws.sheet_state != "visible":
                    continue
                out += _rows_to_records(name, ws.title, [list(r) for r in ws.iter_rows(values_only=True)], kind)
        elif name.lower().endswith(".csv"):
            rows = list(csv.reader(io.StringIO(b.decode("utf-8-sig", errors="replace"))))
            out += _rows_to_records(name, "csv", rows, kind)
    return out


# ================================================================== matching

def _rule_hit(rule: dict, a: dict, b: dict) -> bool:
    attrs = [x.strip() for x in str(rule.get("attributes") or "").split(",") if x.strip()]
    for spec in attrs:
        alts = [s.strip() for s in spec.split("|")]
        ok = False
        for f in alts:
            va, vb = a.get(f), b.get(f)
            if not va or not vb:
                continue
            if f == "name":
                if rule["compare"] == "exact":
                    ok = va == vb
                elif rule["compare"] == "normalised":
                    ok = norm(va) == norm(vb)
                else:
                    ok = similar(va, vb) >= float(rule.get("threshold") or 0.88)
            elif f == "email":
                ok = va.strip().lower() == vb.strip().lower()            # a shared domain is a company, not a record
            else:
                ok = str(va).strip().lower() == str(vb).strip().lower()
            if ok:
                break
        if not ok:
            return False
    return True


def hold_apart(a: dict, b: dict) -> str | None:
    """Why two records are never one, whatever the names say: two different tax ids, or a false friend."""
    if a.get("tax_id") and b.get("tax_id") and str(a["tax_id"]).strip().upper() != str(b["tax_id"]).strip().upper():
        return "two different tax ids"
    if false_friend(a, b):
        return f"same name, but {a['country']} and {b['country']} and no shared tax id or email"
    return None


def false_friend(a: dict, b: dict) -> bool:
    """Same name, but a different country and nothing else shared: two organisations, never one."""
    return bool(norm(a["name"]) == norm(b["name"]) and a.get("country") and b.get("country") and a["country"] != b["country"]
                and not (a.get("tax_id") and a.get("tax_id") == b.get("tax_id")) and not (a.get("email") and (a.get("email") or "").lower() == (b.get("email") or "").lower()))


def pairs(records: list[dict], rules: list[dict] | None = None, refused: set | None = None) -> list[dict]:
    """Candidate duplicates: [{a, b, rule, score, action, why}] - blocking on tax id, normalised name and the name's
    first word with the country; the first enabled rule that holds wins; false friends become 'not a match'."""
    rules = [r for r in (rules or DEFAULT_RULES) if r.get("enabled", True)]
    refused = refused or set()
    blocks: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(records):
        if r.get("tax_id"):
            blocks["t:" + str(r["tax_id"]).upper()].append(i)
        n = norm(r["name"])
        if n:
            blocks["n:" + n].append(i)
            blocks["w:" + n.split()[0] + ":" + str(r.get("country") or "")].append(i)
    seen, out = set(), []
    for ids in blocks.values():
        if len(ids) < 2 or len(ids) > 60:
            continue
        for x in range(len(ids)):
            for y in range(x + 1, len(ids)):
                a, b = records[ids[x]], records[ids[y]]
                k = tuple(sorted((a["id"], b["id"])))
                if k in seen or a["type"] != b["type"]:
                    continue
                seen.add(k)
                if frozenset(k) in refused:
                    continue
                reason = hold_apart(a, b)
                if reason:
                    if norm(a["name"]) == norm(b["name"]) or similar(a["name"], b["name"]) >= 0.88:     # a pair a person might confuse
                        out.append({"a": a["id"], "b": b["id"], "rule": "False-friend guard", "score": 30, "action": "not_match", "why": reason})
                    continue
                for r in rules:
                    if _rule_hit(r, a, b):
                        out.append({"a": a["id"], "b": b["id"], "rule": r["name"], "score": int(r.get("score") or 80), "action": r["action"],
                                    "why": f"{r['name']}: {', '.join(f'{f}={a.get(f.split(chr(124))[0])}' for f in str(r['attributes']).replace(' ', '').split(','))}"[:200]})
                        break
    return sorted(out, key=lambda p: (-p["score"], p["a"], p["b"]))


def survivor(a: dict, b: dict) -> tuple[dict, dict]:
    """Which record survives a merge: the one with more sources, then a tax id, then the older one."""
    def rank(r):
        return (len(r.get("sources") or []), 1 if r.get("tax_id") else 0, -(r.get("created") or 0) if isinstance(r.get("created"), (int, float)) else 0)
    return (a, b) if rank(a) >= rank(b) else (b, a)


def gaps(records: list[dict]) -> list[dict]:
    out = []
    for r in records:
        if r["type"] == "product":
            continue
        miss = [f for f in ("country", "email") if not r.get(f)]
        if r.get("country") == "IN" and not r.get("tax_id"):
            miss.append("tax_id")
        if miss:
            out.append({"id": r["id"], "name": r["name"], "missing": miss})
    return out


def codes_twice(records: list[dict]) -> list[str]:
    c = Counter((r["type"], r.get("code")) for r in records if r.get("code"))
    return sorted(f"{k[1]}" for k, n in c.items() if n > 1)
