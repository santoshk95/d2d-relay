"""Data governance & catalogue — the rules (no agent): catalogue health, the fixes they propose, glossary duplicates,
and the mapping of one catalogue onto another. Everything reads the neutral catalogue of _w1_cat."""
from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from pathlib import Path

from ._w1_cat import CLASS_LABEL, CLASSES, PERSONAL_RX, asset, catalog, key, neutral_class, platform_of

GOVERNED = ("table", "view", "report", "process")
SYNONYMS = {"revenue": "sale", "turnover": "sale", "income": "sale", "client": "customer", "vendor": "supplier", "item": "product", "sku": "product",
            "debtor": "receivable", "stock": "inventory", "%": "pct", "percent": "pct", "percentage": "pct"}
NAME_CLASS = [(r"(?i)E?MAIL", "personal.email"), (r"(?i)PHONE|MOBILE", "personal.phone"), (r"(?i)(FULL_|FIRST_|LAST_|CONTACT_)?NAME$|SURNAME", "personal.name"),
              (r"(?i)DOB|BIRTH", "personal.birthdate"), (r"(?i)ADDRESS|STREET|POST_?CODE|ZIP", "personal.address"), (r"(?i)GSTIN|PAN$|SSN|NI_NUMBER|NATIONAL_ID|PASSPORT", "government.taxid"),
              (r"(?i)IBAN|ACCOUNT_NUMBER", "financial.account")]
MINUTES = {"owner": 2, "personal": 3, "duplicate": 20, "no_definition": 15, "steward": 5, "scan": 30, "deprecated": 30, "uncertified": 15, "description": 5, "lineage": 20}
LABEL = {"owner": "No owner", "personal": "Personal data not classified", "duplicate": "Duplicate term", "no_definition": "Term without a definition",
         "steward": "Term without a steward", "scan": "Scan failing", "deprecated": "Deprecated but still used", "uncertified": "Report not certified",
         "description": "No description", "lineage": "No lineage"}
ROUTE = {"owner": "change", "personal": "change", "duplicate": "change", "no_definition": "change", "steward": "change", "scan": "heal", "deprecated": "ticket",
         "uncertified": "ticket", "description": "change", "lineage": "change"}


def class_of(column: str) -> str | None:
    for rx, cls in NAME_CLASS:
        if re.search(rx, column or ""):
            return cls
    return None


def canon(term: str) -> str:
    """A term's canonical form for duplicates: lower case, words through the synonym table, plurals dropped."""
    words = re.findall(r"[a-z0-9%]+", (term or "").lower())
    one = [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in words]     # plurals first, then synonyms
    return " ".join(SYNONYMS.get(w, w) for w in one)


def schema_of(a: dict) -> str:
    k = a["key"].split(":", 1)[-1]
    return k.split(".")[0] if a["kind"] in ("table", "view") and "." in k else ""


STEMS_OFF = {"STG", "DIM", "FACT", "AGG", "TMP", "V", "VW", "MART", "DW", "STAGE", "BKP", "OLD", "NEW", "X", "T"}


def _about(parent_key: str) -> set:
    """What a table is about, from its name: STAGE.STG_CUSTOMERS -> {CUSTOMER}."""
    name = parent_key.split(":", 1)[-1].split(".")[-1].upper()
    return {w[:-1] if len(w) > 3 and w.endswith("S") else w for w in re.split(r"[_\W]+", name) if w and w not in STEMS_OFF and not w.isdigit()}


LEGACY_RX = re.compile(r"(?i)\b(deprecated|obsolete|retired|backup|copy of|orphan|do not use)\b")


def same_owner(a, b) -> bool:
    """Owners compare by name, ignoring case, spaces and underscores (Atlan keeps groups as data_team)."""
    return bool(a) and bool(b) and re.sub(r"[\s_\-]+", "", str(a).lower()) == re.sub(r"[\s_\-]+", "", str(b).lower())


def same_class(a, b, tool: str) -> bool:
    """Two classifications are the same when the target catalogue names them the same (Atlan has only PII)."""
    if a == b:
        return True
    by_a, by_b = CLASSES.get(a or "", {}), CLASSES.get(b or "", {})
    return bool(by_a and by_b and tool in by_a and by_a.get(tool) == by_b.get(tool))


def health(cat: dict) -> list[dict]:
    """Every finding of the catalogue: [{id, kind, object, name, issue, route, minutes, evidence}]. A catalogue without
    certificates (the Purview Data Map) is judged by its descriptions instead ("2019 copy of …", "backup of …")."""
    out: list[dict] = []
    assets = cat["assets"]
    certs = any(a.get("certified") for a in assets)
    by = {a["key"]: a for a in assets}
    downstream = Counter(e["from"] for e in cat["edges"])
    upstream = Counter(e["to"] for e in cat["edges"])

    def add(kind, a_key, name, issue, ev=None):
        out.append({"id": f"{kind}:{a_key}", "kind": kind, "object": a_key, "name": name, "issue": issue, "route": ROUTE[kind], "minutes": MINUTES[kind], "evidence": ev or {}})
    for a in assets:
        if a["kind"] in GOVERNED and not a.get("owner"):
            add("owner", a["key"], a["name"], f"{a['kind'].title()} {a['name']} has no owner", {"schema": schema_of(a), "platform": a["platform"]})
        legacy = a.get("certified") == "Deprecated" or (not certs and LEGACY_RX.search(a.get("description") or ""))
        if a["kind"] in ("table", "view") and legacy and (downstream.get(a["key"]) or schema_of(a) in ("DW", "MART")):
            add("deprecated", a["key"], a["name"], f"{a['name']} is " + ("certified Deprecated" if a.get("certified") == "Deprecated" else f"described as legacy (“{(a.get('description') or '')[:60]}”)")
                + " but is still " + (f"read by {downstream[a['key']]} object(s)" if downstream.get(a["key"]) else f"in the {schema_of(a)} schema"),
                {"downstream": [e["to"] for e in cat["edges"] if e["from"] == a["key"]][:10]})
        if a["kind"] == "report" and certs and a.get("certified") != "Certified":
            add("uncertified", a["key"], a["name"], f"The report {a['name']} is not certified")
        if a["kind"] == "report" and not upstream.get(a["key"]) and cat["edges"]:
            add("lineage", a["key"], a["name"], f"The report {a['name']} has no lineage to its tables")
        if a["kind"] in ("table", "view") and schema_of(a) in ("DW", "MART") and not a.get("description") and not legacy:
            add("description", a["key"], a["name"], f"{a['name']} has no description")
    # personal data: a column whose name says so, or whose twin (the same name in a table about the same thing, e.g.
    # STG_CUSTOMERS.EMAIL and CUSTOMERS.EMAIL) is classified elsewhere
    twins: dict[str, list[tuple[set, str]]] = {}
    for a in assets:
        if a["kind"] == "column" and a.get("classification"):
            twins.setdefault(a["name"].upper(), []).append((_about(a.get("parent") or ""), a["classification"]))
    for a in assets:
        if a["kind"] != "column" or a.get("classification"):
            continue
        about = _about(a.get("parent") or "")
        twin = Counter(cls for words, cls in twins.get(a["name"].upper(), []) if words & about or not about)
        by_name = class_of(a["name"]) if PERSONAL_RX.match(a["name"]) else None
        if twin or (by_name and by_name != "personal.name") or (by_name == "personal.name" and a["name"].upper() != "NAME"):
            cls = twin.most_common(1)[0][0] if twin else by_name
            parent = by.get(a.get("parent") or "", {}).get("name") or (a.get("parent") or "").split(":")[-1]
            add("personal", a["key"], f"{parent}.{a['name']}" if parent else a["name"], f"{parent + '.' if parent else ''}{a['name']} looks like {CLASS_LABEL.get(cls, cls).lower()} but is not classified"
                + (f" — {sum(twin.values())} column(s) of the same name are" if twin else ""), {"proposed": cls, "twins": sum(twin.values()) if twin else 0})
    # the glossary
    terms = cat["terms"]
    groups: dict[str, list[dict]] = {}
    for t in terms:
        if t.get("status") != "Obsolete":
            groups.setdefault(canon(t["name"]).replace("net ", "").strip(), []).append(t)
    for g, ts in groups.items():
        if len(ts) > 1:
            keep = sorted(ts, key=lambda t: (t.get("status") != "Approved", not t.get("definition"), t["name"]))[0]
            for t in ts:
                if t is not keep:
                    add("duplicate", f"term:{t['name']}", t["name"], f"The term “{t['name']}” duplicates “{keep['name']}”", {"keep": keep["name"], "definition": keep.get("definition")})
    for t in terms:
        if t.get("status") == "Obsolete":
            continue
        if not (t.get("definition") or "").strip():
            add("no_definition", f"term:{t['name']}", t["name"], f"The term “{t['name']}” has no definition")
        if not t.get("steward") and (t.get("definition") or "").strip():
            add("steward", f"term:{t['name']}", t["name"], f"The term “{t['name']}” has no steward")
    # scans: the latest run of each source
    last: dict[str, dict] = {}
    for s in cat["scans"]:
        if str(s.get("start") or "") >= str((last.get(s["source"]) or {}).get("start") or ""):
            last[s["source"]] = s
    for src, s in last.items():
        if str(s.get("status") or "").lower() in ("failed", "failure", "error"):
            add("scan", f"scan:{src}", src, f"The scan of {src} failed on its last run: {(s.get('error') or 'no message')[:200]}", {"error": s.get("error"), "start": s.get("start")})
    return out


def propose(finding: dict, cat: dict, learned: list[dict]) -> dict:
    """The fix a finding asks for, by rules: {change, value, why}. An empty value means a person (or the agent) says it."""
    by = {a["key"]: a for a in cat["assets"]}
    k = finding["kind"]
    a = by.get(finding["object"]) or {}
    subject = schema_of(a) if k == "owner" else (a.get("name") or finding["name"]).split(".")[-1]
    for r in learned:                                      # a fix people approved before wins (by column name, or by schema for owners)
        if r["kind"] == k and subject and re.fullmatch(r["pattern"], subject, re.I):
            return {"change": r["change"], "value": r["value"], "why": f"kept as a rule after {r['item']} was approved"}
    if k == "owner":
        sib = Counter(x["owner"] for x in cat["assets"] if x["kind"] in GOVERNED and x.get("owner") and schema_of(x) == schema_of(a) and x["platform"] == a.get("platform") and schema_of(a))
        if sib:
            return {"change": "owner", "value": sib.most_common(1)[0][0], "why": f"the owner of the other {schema_of(a)} objects"}
        plat = Counter(x["owner"] for x in cat["assets"] if x["kind"] in GOVERNED and x.get("owner") and x["platform"] == a.get("platform"))
        if plat:
            return {"change": "owner", "value": plat.most_common(1)[0][0], "why": f"the most common owner on {a.get('platform')}"}
        return {"change": "owner", "value": "", "why": "nobody owns anything near it — say who"}
    if k == "personal":
        return {"change": "classify", "value": finding["evidence"].get("proposed") or "personal", "why": "the column of the same name is classified" if finding["evidence"].get("twins") else "its name"}
    if k == "duplicate":
        return {"change": "retire_term", "value": finding["evidence"].get("keep", ""), "why": f"keep “{finding['evidence'].get('keep')}”, retire the duplicate"}
    if k == "no_definition":
        return {"change": "define", "value": "", "why": "no rule defines a term — Relay's agent drafts it from the metrics and the glossary"}
    if k == "description":
        return {"change": "describe", "value": "", "why": "Relay's agent drafts it from the columns and the lineage"}
    if k == "steward":
        return {"change": "steward", "value": "", "why": "say who stewards it"}
    if k == "scan":
        return {"change": "rescan", "value": "", "why": "renew the scan's credential, then run it again (Self-healing)"}
    return {"change": "ticket", "value": "", "why": "a decision for the data owner"}


def from_files(paths: list[Path]) -> dict:
    """A catalogue export: an Atlas JSON (Purview, Atlan or Apache Atlas: entities, glossary terms, lineage) or a Collibra
    CSV export (Name, Asset Type, Domain, Status, Description, Owner, Classification, Full Name)."""
    import zipfile
    cat = catalog(tool="export")
    blobs: list[tuple[str, bytes]] = []
    for p in paths:
        if p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as z:
                blobs += [(n, z.read(n)) for n in z.namelist() if not n.endswith("/")]
        else:
            blobs.append((p.name, p.read_bytes()))
    for name, b in blobs:
        text = b.decode("utf-8-sig", errors="replace")
        if name.lower().endswith(".json"):
            _atlas(json.loads(text), cat)
        elif name.lower().endswith(".csv"):
            _collibra_csv(text, cat)
    return cat


def _atlas(doc: dict, cat: dict) -> None:
    kinds = {"table": "table", "view": "view", "column": "column", "process": "process", "report": "report", "package": "process", "schema": "schema"}
    for e in doc.get("entities") or []:
        tn = (e.get("typeName") or "").lower()
        kind = next((v for k_, v in kinds.items() if tn.endswith(k_)), None) or next((v for k_, v in kinds.items() if k_ in tn), None)
        if not kind:
            continue
        at = e.get("attributes") or {}
        q = at.get("qualifiedName") or ""
        plat = "powerbi" if kind == "report" else "ssis" if kind == "process" else platform_of(tn + " " + q)
        from ._w1_cat import _from_qualified
        k, parent = _from_qualified(kind, at.get("name") or "", q, plat)
        own = ((e.get("contacts") or {}).get("Owner") or [{}])[0]
        cat["assets"].append(asset(key=k, id=e.get("guid") or q, kind=kind, name=at.get("name") or "", platform=plat, parent=parent, owner=own.get("info") or own.get("id"),
                                   description=at.get("description"), classification=neutral_class(((e.get("classifications") or [{}])[0]).get("typeName")),
                                   certified=at.get("certified"), rows=at.get("rowCount"), qualified=q, type=e.get("typeName")))
    by_q = {a["qualified"]: a["key"] for a in cat["assets"]}
    for r in doc.get("lineage") or []:
        if by_q.get(r.get("from")) and by_q.get(r.get("to")):
            cat["edges"].append({"from": by_q[r["from"]], "to": by_q[r["to"]], "via": by_q.get(r.get("via"))})
    for t in doc.get("terms") or []:
        cat["terms"].append({"id": t.get("guid") or t["name"], "name": t["name"], "definition": t.get("longDescription") or t.get("definition") or "", "status": t.get("status") or "Draft",
                             "steward": t.get("steward")})
    for s in doc.get("scans") or []:
        cat["scans"].append({"source": s.get("source"), "scan": s.get("scan"), "status": s.get("status"), "start": s.get("start"), "end": s.get("end"), "error": s.get("error")})


def _collibra_csv(text: str, cat: dict) -> None:
    kinds = {"table": "table", "database view": "view", "column": "column", "data process": "process", "report": "report"}
    for r in csv.DictReader(io.StringIO(text)):
        ty = (r.get("Asset Type") or "").strip().lower()
        if ty == "business term":
            st = r.get("Status") or ""
            cat["terms"].append({"id": r.get("Full Name") or r["Name"], "name": r["Name"], "definition": r.get("Description") or "", "status": {"Accepted": "Approved", "Obsolete": "Obsolete"}.get(st, "Draft"),
                                 "steward": r.get("Owner") or None})
            continue
        kind = kinds.get(ty)
        if not kind:
            continue
        plat = "powerbi" if kind == "report" else "ssis" if kind == "process" else platform_of(r.get("Domain") or "")
        full = (r.get("Full Name") or r["Name"]).split(">")[-1].strip()
        parts = [p for p in re.split(r"[./]", full) if p]
        k = key(plat, *parts[-3:]) if kind == "column" else key(plat, *parts[-2:]) if kind in ("table", "view") else key(plat, r["Name"])
        cat["assets"].append(asset(key=k, id=r.get("Full Name") or r["Name"], kind=kind, name=r["Name"], platform=plat, parent=key(plat, *parts[-3:-1]) if kind == "column" else None,
                                   owner=r.get("Owner") or None, description=r.get("Description") or None, classification=neutral_class(r.get("Classification")),
                                   certified={"Accepted": "Certified", "Obsolete": "Deprecated"}.get(r.get("Status") or ""), qualified=full, type=r.get("Asset Type")))


def match(src: dict, dst: dict) -> dict[str, str]:
    """Source asset key -> target asset key: the same platform, kind and name (and schema where both catalogues know it)."""
    idx: dict[tuple, list[dict]] = {}
    for b in dst["assets"]:
        idx.setdefault((b["platform"], b["kind"], b["name"].upper()), []).append(b)
    out = {}
    for a in src["assets"]:
        cands = idx.get((a["platform"], a["kind"], a["name"].upper())) or []
        if a["kind"] == "column":
            pa = (a.get("parent") or "").split(":")[-1]
            cands = [b for b in cands if pa in ("", "?") or (b.get("parent") or "").endswith(pa)] or ([] if "?" not in a["key"] else cands[:1])
        elif "." in a["key"].split(":", 1)[-1]:
            same = [b for b in cands if b["key"] == a["key"]]
            cands = same or cands
        if cands:
            out[a["key"]] = cands[0]["key"]
    return out
