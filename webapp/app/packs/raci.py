"""RACI & operating model (registry id `raci`) - who is Responsible, Accountable, Consulted and Informed for each
activity of a process, agents included as roles; conflicts flagged (two Accountables, nobody Responsible, an agent
Accountable); each owner confirms their rows; published with the operating model; approvals in Relay follow it.

Develop  Processes -> Roles -> Draft -> Agree -> Publish -> Use. The activities come from a published process (Business
         process documents) or an uploaded list; the roles from the process's lanes (people, agents, systems), an org
         chart and Entra ID group exports. Draft is rules first: the lane that does an activity is Responsible, the
         manager role of its people (or the process owner) Accountable - an agent is never Accountable - the lane that
         hands the work over is Consulted, the lane that takes it next Informed; a matrix with a conflict cannot be
         confirmed. Agree asks each Accountable owner to confirm their rows (a checkpoint each). Publish writes the
         matrix (Excel) and the operating model (Word, the tenant's template), versions kept; Use records the routing
         so Relay's approvals follow it (a process change's approver is the Accountable of that process).
Assess   Connect -> Inventory -> Health -> Findings -> Estimate over existing RACI spreadsheets.
Change   Request -> Diagnose -> Fix -> Prove -> Approve -> Learn on a published model.
Published models are kept in `raci_models` / `raci_versions`; `accountable(process, activity)` is what other packs ask.
"""
from __future__ import annotations

import io
import json
import re
import secrets as _secrets
import time
from pathlib import Path

from .. import auth, db
from .. import workbench as wb
from . import _w4

MODULE = "raci"
SYSTEM = "Relay roles"
LETTERS = ("R", "A", "C", "I")
KINDS = (("person", "Person"), ("agent", "Agent (Relay or a bot)"), ("system", "System"))
AGENT_RE = re.compile(r"\b(bot|robot|agent|rpa|relay|automation)\b", re.I)
PROCESS_ROW = "(the process)"
UPLOADS = (".csv", ".tsv", ".xlsx")

db.register_schema("""
CREATE TABLE IF NOT EXISTS raci_models (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, item TEXT, process_id TEXT, version INTEGER NOT NULL DEFAULT 1, matrix TEXT NOT NULL, roles TEXT NOT NULL,
  owner_id TEXT, published_by TEXT, published REAL, created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS raci_versions (
  model_id TEXT NOT NULL, version INTEGER NOT NULL, item TEXT, matrix TEXT NOT NULL, roles TEXT NOT NULL, published_by TEXT, published REAL NOT NULL, note TEXT,
  PRIMARY KEY (model_id, version));
CREATE TABLE IF NOT EXISTS raci_routes (
  model_id TEXT NOT NULL, process_id TEXT, activity TEXT NOT NULL, accountable TEXT NOT NULL, responsible TEXT, users TEXT NOT NULL DEFAULT '[]', updated REAL NOT NULL,
  PRIMARY KEY (model_id, activity));
""")

FILES = wb.FilesPlatform()
FILES.label = "Org charts, Entra ID group exports, activity lists and RACI sheets"
FILES.uploads = UPLOADS
FILES.reads = "an org chart (name, e-mail, title, manager), Entra ID groups (group, member), a list of activities, or an existing RACI sheet - a copy in this work item's folder"
FILES.simulator = "synthetic fixtures in tests/mocklab/fixtures/raci/ (org chart, Entra ID groups, a 2023 RACI sheet with seeded conflicts)"


# ------------------------------------------------------------------ the published models (versions kept) and the routing others ask

def model(mid: str, u: dict | None = None) -> dict | None:
    r = db.one("SELECT * FROM raci_models WHERE id = ?", (mid,))
    if not r:
        return None
    if u is not None and r.get("item") and not auth.can_project(u, "view", db.project(r["item"])):
        return None
    return {**r, "matrix": _w4.j(r["matrix"], []), "roles": _w4.j(r["roles"], [])}


def models(u: dict) -> list[dict]:
    rows = [{**r, "matrix": _w4.j(r["matrix"], []), "roles": _w4.j(r["roles"], [])} for r in db.q("SELECT * FROM raci_models ORDER BY updated DESC")]
    return _w4.visible_items(u, rows)


def model_options(u: dict) -> list[tuple[str, str]]:
    return [(m["id"], f"{m['name']} - version {m['version']} - {len(m['matrix'])} activities") for m in models(u)]


def accountable(process_id: str, activity: str | None = None) -> list[str]:
    """The Relay people Accountable for a process (one activity, or the process as a whole: its owner rows first) - so
    approvals elsewhere in Relay follow the published RACI."""
    rows = db.q("SELECT * FROM raci_routes WHERE process_id = ? ORDER BY activity", (process_id,))
    if activity:
        rows = [r for r in rows if _w4.name_key(r["activity"]) == _w4.name_key(activity)] or rows
    else:                                                  # the process as a whole: its owner's row (the activities' only when there is none)
        rows = [r for r in rows if r["activity"] == PROCESS_ROW] or rows
    out = []
    for r in rows:
        for uid in _w4.j(r["users"], []):
            if uid not in out:
                out.append(uid)
    return out


def _process_options(u: dict) -> list[tuple[str, str]]:
    try:
        from . import processdocs
        return [("", "None - I upload a list of activities")] + processdocs.process_options(u)
    except Exception:  # noqa: BLE001 - Business process documents not here: upload the activities
        return [("", "None - I upload a list of activities")]


# ------------------------------------------------------------------ reading uploads: org chart, Entra ID groups, activity lists, RACI sheets

def _rows(path: Path) -> list[dict]:
    if path.suffix.lower() == ".xlsx":
        import openpyxl
        book = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        raw = [["" if v is None else str(v).strip() for v in r] for r in book.worksheets[0].iter_rows(values_only=True)]
        book.close()
    else:
        import csv
        with path.open(encoding="utf-8-sig", newline="", errors="replace") as fh:
            raw = [[c.strip() for c in r] for r in csv.reader(fh, delimiter="\t" if path.suffix.lower() == ".tsv" else ",")]
    raw = [r for r in raw if any(r)]
    if not raw:
        return []
    head = [h.strip() for h in raw[0]]
    return [dict(zip(head, r + [""] * (len(head) - len(r)))) for r in raw[1:]]


def _col(row: dict, *names) -> str:
    low = {k.lower().strip(): v for k, v in row.items()}
    return next((str(low[n]).strip() for n in names if n in low and str(low[n]).strip()), "")


def classify(ctx: wb.Ctx) -> dict:
    """Each upload as what it is: an org chart, Entra ID groups, a RACI sheet or a list of activities."""
    out = {"org": [], "groups": [], "sheets": [], "activities": []}
    for f in ctx.files(UPLOADS):
        if f["name"].endswith(".xlsx.csv"):
            continue
        rows = _rows(ctx.dir / "data" / f["name"])
        if not rows:
            continue
        keys = {k.lower() for k in rows[0]}
        if {"email", "title"} <= keys or {"email", "role"} <= keys:
            out["org"].append((f["name"], rows))
        elif ("group" in keys or "displayname" in keys) and ("member" in keys or "member_email" in keys or "mail" in keys):
            out["groups"].append((f["name"], rows))
        elif any(k in keys for k in ("activity", "task", "step")) and sum(1 for r in rows for v in list(r.values())[1:] if str(v).strip().upper().replace("/", "") in ("R", "A", "C", "I", "RA", "AR")) >= 2:
            out["sheets"].append((f["name"], rows))
        elif any(k in keys for k in ("activity", "task", "step")):
            out["activities"].append((f["name"], rows))
    return out


def parse_sheet(rows: list[dict]) -> tuple[list[str], list[dict]]:
    """A RACI sheet: an activity column, a column per role, cells R / A / C / I (or combinations: A/R, RA)."""
    head = list(rows[0].keys())
    act = next(h for h in head if h.lower() in ("activity", "task", "step"))
    proc = next((h for h in head if h.lower() == "process"), None)
    roles = [h for h in head if h not in (act, proc) and h.strip()]
    out = []
    for i, r in enumerate(rows, 1):
        letters = {L: [] for L in LETTERS}
        for role in roles:
            for L in re.findall(r"[RACI]", str(r.get(role) or "").upper()):
                letters[L].append(role)
        out.append({"id": f"A{i}", "activity": str(r.get(act) or "").strip(), "process": str(r.get(proc) or "") if proc else "", **{L: ", ".join(v) for L, v in letters.items()}})
    return roles, [x for x in out if x["activity"]]


# ------------------------------------------------------------------ the rules: conflicts

def split(v) -> list[str]:
    return [x.strip() for x in re.split(r"[,;/]", str(v or "")) if x.strip()]


def conflicts(row: dict, kinds: dict | None = None) -> list[str]:
    """What is wrong with one row: two Accountables, nobody Accountable, nobody Responsible, an agent Accountable, a
    role both Accountable and only Informed, and (with the roles known) a role that is not one of them."""
    a, r = split(row.get("A")), split(row.get("R"))
    out = []
    if len(a) > 1:
        out.append(f"two Accountables ({', '.join(a)})")
    if not a:
        out.append("no one Accountable")
    if not r:
        out.append("no one Responsible")
    for x in a:
        if (kinds or {}).get(x.lower()) == "agent" or (kinds is None and AGENT_RE.search(x)):
            out.append(f"{x} is an agent: an agent can be Responsible, never Accountable")
    if kinds is not None:
        for L in LETTERS:
            for x in split(row.get(L)):
                if x.lower() not in kinds:
                    out.append(f"{x} ({L}) is not one of the roles")
    return out


# ------------------------------------------------------------------ Develop

def d_processes(ctx: wb.Ctx) -> dict:
    acts, lanes, src = [], [], ""
    pid = ctx.scope.get("process") or ""
    if pid:
        from . import processdocs
        p = processdocs.process(pid, db.user(ctx.owner or "") or {})
        if not p:
            raise wb.StepFailed("The published process is not one this work item's owner can see.")
        lanes = p["map"].get("lanes") or []
        lane = {l["id"]: l for l in lanes}
        steps = p["map"]["steps"]
        prev: dict = {}
        for s in steps:
            for n in s.get("next") or []:
                prev.setdefault(n["to"], []).append(s["id"])
        by = {s["id"]: s for s in steps}
        for s in steps:
            if s["type"] in ("start", "end"):
                continue
            acts.append({"id": s["id"], "activity": s["name"], "kind": "decision" if s["type"] == "gateway" else "activity", "lane": (lane.get(s["lane"]) or {}).get("name") or "",
                         "lane_kind": (lane.get(s["lane"]) or {}).get("kind") or "person", "system": s.get("system") or "",
                         "before": sorted({(lane.get(by[x]["lane"]) or {}).get("name") or "" for x in prev.get(s["id"], []) if by[x]["type"] != "start"} - {""}),
                         "after": sorted({(lane.get((by.get(n["to"]) or {}).get("lane")) or {}).get("name") or "" for n in s.get("next") or [] if (by.get(n["to"]) or {}).get("type") != "end"} - {""})})
        ctx.put("process", {"id": p["id"], "name": p["name"], "version": p["version"], "owner": ((p["map"].get("head") or {}).get("owner")) or ""})
        src = f"\"{p['name']}\" version {p['version']}"
    up = classify(ctx)
    for name, rows in up["activities"]:
        for i, r in enumerate(rows, 1):
            a = _col(r, "activity", "task", "step")
            if a:
                acts.append({"id": f"U{len(acts) + 1}", "activity": a, "kind": "activity", "lane": _col(r, "role", "lane", "who"), "lane_kind": "agent" if AGENT_RE.search(_col(r, "role", "lane", "who")) else "person",
                             "system": _col(r, "system"), "before": [], "after": [], "from": f"{name} row {i + 1}"})
        src += (", " if src else "") + name
    if not acts:
        raise wb.StepFailed("No activities: pick a published process (Business process documents) or upload a list of activities (CSV or Excel with an \"activity\" column).")
    ctx.put("activities", acts)
    ctx.put("lanes", lanes)
    return {"summary": f"{len(acts)} activit{'y' if len(acts) == 1 else 'ies'} from {src}, {sum(1 for a in acts if a['kind'] == 'decision')} of them decisions.",
            "counts": {"activities": len(acts)}, "data": {"columns": ["Activity", "Kind", "Lane", "System", "Hands over from", "Hands over to"],
                                                         "rows": [[a["activity"], a["kind"], a["lane"], a["system"], ", ".join(a["before"]), ", ".join(a["after"])] for a in acts]}}


def d_roles(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    up = classify(ctx)
    roles: dict = {}

    def add(name, kind, source, people=(), manager=""):
        k = name.strip().lower()
        if not k:
            return
        r = roles.setdefault(k, {"id": f"role-{_w4.slug(name, 30)}", "role": name.strip(), "kind": kind, "people": [], "source": source, "manager": manager})
        r["people"] = sorted(set(r["people"]) | {p for p in people if p})
        if manager and not r["manager"]:
            r["manager"] = manager
        if source not in r["source"]:
            r["source"] += f"; {source}"
    for l in ctx.get("lanes") or []:
        add(l["name"], l.get("kind") or "person", "the process map's lanes")
    for a in ctx.get("activities") or []:
        if a["lane"]:
            add(a["lane"], a["lane_kind"], "the activity list")
    owner = (ctx.get("process") or {}).get("owner")
    if owner:
        add(owner, "person", "the process owner")
    by_email = {}
    for name, rows in up["org"]:
        for r in rows:
            by_email[_col(r, "email", "mail").lower()] = r
    for name, rows in up["org"]:
        for r in rows:
            mgr = by_email.get(_col(r, "manager_email", "manager").lower()) or {}
            add(_col(r, "title", "role"), "person", f"org chart {name}", [_col(r, "email", "mail").lower()], _col(mgr, "title", "role"))
    for name, rows in up["groups"]:
        for r in rows:
            add(_col(r, "group", "displayname"), "person", f"Entra ID groups {name}", [_col(r, "member_email", "member", "mail").lower()])
    if any(a["lane_kind"] == "agent" for a in ctx.get("activities") or []) or any(a.get("system") for a in ctx.get("activities") or []):
        add("Relay agent", "agent", "Relay: the agents that do steps people validate")
    users = {u["email"].lower(): u for u in db.q("SELECT id, email, name FROM users WHERE active = 1")}
    recs = []
    for r in roles.values():
        rec = {**r, "people": ", ".join(r["people"]), "relay": ", ".join(users[p]["name"] for p in r["people"] if p in users)}
        recs.append({**rec, **{k: have[rec["id"]][k] for k in ("kind", "people") if rec["id"] in have}})
    return {"summary": f"{len(recs)} role(s): {sum(1 for r in recs if r['kind'] == 'person')} for people, {sum(1 for r in recs if r['kind'] == 'agent')} for agents, "
            f"{sum(1 for r in recs if r['kind'] == 'system')} for systems - agents are roles too. Correct them, then confirm.",
            "records": recs, "counts": {"roles": len(recs)}, "data": {"columns": ["Role", "Kind", "People", "In Relay", "Reports to", "From"],
                                                                     "rows": [[r["role"], r["kind"], r["people"], r["relay"], r["manager"], r["source"]] for r in recs]}}


def _validate_roles(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    out, seen = [], set()
    for r in recs:
        if not str(r.get("role") or "").strip():
            out.append("a role needs a name")
        elif r["role"].strip().lower() in seen:
            out.append(f"{r['role']}: the role is listed twice")
        seen.add(str(r.get("role") or "").strip().lower())
        if r.get("kind") not in dict(KINDS):
            out.append(f"{r.get('role')}: pick person, agent or system")
        if not r.get("id"):
            r["id"] = f"role-{_w4.slug(r.get('role') or 'role', 30)}"
    return out


ROLE_EDIT = wb.Edit(columns=[wb.Column("role", "Role"), wb.Column("kind", "Kind", "select", options=KINDS), wb.Column("people", "People (e-mails)", "longtext"),
                             wb.Column("manager", "Reports to (role)"), wb.Column("source", "From", readonly=True)], validate=_validate_roles, label="role")


def _kinds(ctx: wb.Ctx) -> dict:
    return {r["role"].strip().lower(): r["kind"] for r in ctx.records("roles")}


def draft_rows(ctx: wb.Ctx) -> list[dict]:
    """Rules first: the lane that does it is Responsible; the role its people report to (else the process owner) is
    Accountable - never an agent; who hands it over is Consulted; who takes it next is Informed."""
    roles = {r["role"].strip().lower(): r for r in ctx.records("roles")}
    owner = (ctx.get("process") or {}).get("owner") or ""
    out = []
    for a in ctx.get("activities") or []:
        r_role = a["lane"] or owner
        lane = roles.get(r_role.lower()) or {}
        acc = lane.get("manager") or owner or r_role
        if (roles.get(acc.lower()) or {}).get("kind") == "agent" or acc.lower() == r_role.lower() and lane.get("kind") == "agent":
            acc = owner or acc
        if a["kind"] == "decision" and owner:
            acc = owner if (roles.get(owner.lower()) or {}).get("kind") != "agent" else acc
        cons = [x for x in a["before"] if x.lower() not in (r_role.lower(), acc.lower())]
        info = [x for x in a["after"] if x.lower() not in (r_role.lower(), acc.lower()) and x not in cons]
        why = f"R: the {r_role} lane does it; A: " + ("the role its people report to" if lane.get("manager") and acc == lane.get("manager") else "the process owner") + \
              ("; C: hands it over" if cons else "") + ("; I: takes it next" if info else "")
        out.append({"id": a["id"], "activity": a["activity"], "R": r_role, "A": acc, "C": ", ".join(cons), "I": ", ".join(info), "why": why})
    return out


def d_draft(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    rows = [{**r, **{L: have[r["id"]][L] for L in LETTERS if r["id"] in have}} for r in draft_rows(ctx)]
    kinds = _kinds(ctx)
    for r in rows:
        r["problem"] = "; ".join(conflicts(r, kinds))
    bad = [r for r in rows if r["problem"]]
    return {"summary": f"{len(rows)} row(s) drafted by the rules" + (f"; {len(bad)} with a conflict, highlighted - resolve them before you confirm" if bad else "; no conflicts") + ".",
            "records": rows, "counts": {"activities": len(rows), "conflicts": len(bad)}, "data": _matrix_table(rows, kinds),
            "items": [f"{r['activity']}: {r['problem']}" for r in bad[:6]]}


def _matrix_table(rows: list[dict], kinds: dict) -> dict:
    roles = sorted({x for r in rows for L in LETTERS for x in split(r.get(L))}, key=lambda x: (kinds.get(x.lower()) != "person", x.lower()))
    cell = lambda r, role: "".join(L for L in LETTERS if role in split(r.get(L)))  # noqa: E731
    return {"columns": ["Activity", *roles[:8], "Conflicts"], "rows": [[r["activity"], *[cell(r, x) for x in roles[:8]], r.get("problem") or ""] for r in rows]}


def _validate_matrix(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    """A matrix with a conflict cannot be confirmed (rules first): two Accountables, nobody Accountable or Responsible,
    an agent Accountable, a role that is not one of the roles."""
    kinds = _kinds(ctx) or None
    out = []
    for r in recs:
        p = conflicts(r, kinds)
        r["problem"] = "; ".join(p)
        out += [f"{r.get('activity')}: {x}" for x in p]
    return out


MATRIX_EDIT = wb.Edit(columns=[wb.Column("activity", "Activity", readonly=True), wb.Column("R", "Responsible"), wb.Column("A", "Accountable"), wb.Column("C", "Consulted"),
                               wb.Column("I", "Informed"), wb.Column("problem", "Conflicts", readonly=True)], add=False, remove=False, validate=_validate_matrix, label="row")


def d_agree(ctx: wb.Ctx) -> dict:
    roles = {r["role"].strip().lower(): r for r in ctx.records("roles")}
    rows = ctx.records("draft")
    users = {u["email"].lower(): u for u in db.q("SELECT id, email, name FROM users WHERE active = 1")}
    owners: dict = {}
    for r in rows:
        for a in split(r["A"]):
            for p in split((roles.get(a.lower()) or {}).get("people")):
                if p.lower() in users:
                    owners.setdefault(users[p.lower()]["id"], {"user": users[p.lower()], "role": a, "rows": []})["rows"].append(r["activity"])
    n = int(ctx.get("round_n") or 0) + 1
    ctx.put("round_n", n)
    ctx.put("round", f"r{n}")
    for o in owners.values():
        _w4.ask_signoff(ctx, [o["user"]], round_=f"r{n}", what=f"Your rows of the RACI for {ctx.title}: you are Accountable for {len(o['rows'])} activit{'y' if len(o['rows']) == 1 else 'ies'}.",
                        items=[f"{x}: Accountable - {o['role']}" for x in o["rows"]], role=o["role"])
    ctx.put("owners", {uid: {"role": o["role"], "rows": o["rows"]} for uid, o in owners.items()})
    unowned = sorted({a for r in rows for a in split(r["A"]) if not any(o["role"] == a for o in owners.values())})
    ctx.put("unowned", unowned)
    return _agree_view(ctx)


def _agree_view(ctx: wb.Ctx) -> dict:
    owners = ctx.get("owners") or {}
    recs = []
    for r in _w4.signoff_records(ctx.id, "agree", ctx.get("round") or "r1"):
        o = owners.get(r["id"]) or {}
        recs.append({**r, "rows": ", ".join(o.get("rows") or [])})
    for a in ctx.get("unowned") or []:
        recs.append({"id": f"none-{_w4.slug(a)}", "person": "-", "role": a, "decision": "no Relay user in this role: the work item's owner confirms it", "when": "", "comment": "", "rows": ""})
    done = sum(1 for r in recs if r["decision"] == "signed off")
    return {"summary": f"{done} of {sum(1 for r in recs if r['person'] != '-')} owner(s) confirmed their rows" + (f"; {len(ctx.get('unowned') or [])} role(s) without a Relay user" if ctx.get("unowned") else "") + ".",
            "records": recs, "counts": {"owners": len(owners), "confirmed": done}, "data": {"columns": ["Owner", "Role", "Rows", "Decision", "When", "Comment"],
                                                                                         "rows": [[r["person"], r["role"], r["rows"], r["decision"], r["when"], r["comment"]] for r in recs]}}


_w4.REFRESH["raci.agree"] = _agree_view


def _validate_agree(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    return _w4.signoff_problems(ctx.id, "agree", ctx.get("round") or "r1")


AGREE_EDIT = wb.Edit(columns=[wb.Column("person", "Owner", readonly=True), wb.Column("role", "Role", readonly=True), wb.Column("rows", "Their rows", readonly=True),
                              wb.Column("decision", "Decision", readonly=True), wb.Column("when", "When", readonly=True), wb.Column("comment", "Comment", readonly=True)],
                     add=False, remove=False, validate=_validate_agree, label="owner")


def _xlsx(rows: list[dict], kinds: dict) -> bytes:
    import openpyxl
    from openpyxl.styles import Font
    t = _matrix_table(rows, kinds)
    book = openpyxl.Workbook()
    ws = book.active
    ws.title = "RACI"
    ws.append(t["columns"][:-1])
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in t["rows"]:
        ws.append(r[:-1])
    ws2 = book.create_sheet("Roles")
    ws2.append(["Role", "Kind"])
    for k, v in kinds.items():
        ws2.append([k, v])
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def publish(ctx: wb.Ctx, rows: list[dict], roles: list[dict], mid: str | None, note: str = "") -> dict:
    now = time.time()
    who = ctx.who or ctx.owner
    clean = [{k: r.get(k) for k in ("id", "activity", "R", "A", "C", "I")} for r in rows]
    rl = [{k: r.get(k) for k in ("role", "kind", "people", "manager")} for r in roles]
    pid = (ctx.get("process") or {}).get("id")
    if mid and db.one("SELECT 1 FROM raci_models WHERE id = ?", (mid,)):
        v = db.one("SELECT version FROM raci_models WHERE id = ?", (mid,))["version"] + 1
        db.run("UPDATE raci_models SET version = ?, matrix = ?, roles = ?, published_by = ?, published = ?, updated = ? WHERE id = ?", (v, json.dumps(clean), json.dumps(rl), who, now, now, mid))
    else:
        mid, v = "raci-" + _secrets.token_hex(4), 1
        db.run("INSERT INTO raci_models (id, name, item, process_id, version, matrix, roles, owner_id, published_by, published, created, updated) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)",
               (mid, ctx.title[:160], ctx.id, pid, json.dumps(clean), json.dumps(rl), ctx.owner, who, now, now, now))
    db.run("INSERT OR REPLACE INTO raci_versions (model_id, version, item, matrix, roles, published_by, published, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
           (mid, v, ctx.id, json.dumps(clean), json.dumps(rl), who, now, note[:500] or None))
    db.audit("raci.publish", mid, {"version": v, "rows": len(clean), "item": ctx.id}, who)
    return model(mid)


def d_publish(ctx: wb.Ctx, rows: list[dict] | None = None, note: str = "") -> dict:
    rows = rows if rows is not None else ctx.records("draft")
    roles = ctx.records("roles") or (model(ctx.get("model") or "") or {}).get("roles") or []
    kinds = {r["role"].strip().lower(): r["kind"] for r in roles}
    probs = [p for r in rows for p in conflicts(r, kinds or None)]
    if probs:
        raise wb.StepFailed("The matrix still has conflicts: " + "; ".join(probs[:4]))
    m = publish(ctx, rows, roles, ctx.get("model") or ctx.scope.get("model"), note=note or f"published from {ctx.id}")
    ctx.put("model", m["id"])
    v = m["version"]
    ctx.output(f"raci-v{v}.xlsx", _xlsx(rows, kinds), label=f"The RACI matrix, version {v} (Excel)")
    signed = _w4.signoff_records(ctx.id, "agree", ctx.get("round") or "r1")
    rec = {"rows": rows, "roles": roles, "signed": signed}
    t = _matrix_table(rows, kinds)
    secs = [{"title": "Who does, approves and is told", "blocks": [_w4.table(t["columns"][:-1], [r[:-1] for r in t["rows"]], f"record:raci-v{v}#rows", "R Responsible - A Accountable - C Consulted - I Informed")]},
            {"title": "Roles", "blocks": [_w4.table(["Role", "Kind", "People", "Reports to"], [[r["role"], r["kind"], r.get("people") or "", r.get("manager") or ""] for r in roles], f"record:raci-v{v}#roles",
                                                    "People, agents and systems - an agent is never Accountable")]},
            {"title": "Agreed by", "blocks": [_w4.table(["Owner", "Role", "Decision", "When"], [[s["person"], s["role"], s["decision"], s["when"]] for s in signed] or [["-", "-", "the work item's owner", ""]],
                                                        f"record:raci-v{v}#signed", "Each owner confirmed their rows")]}]
    info = _w4.build_doc(ctx, f"operating-model-v{v}", f"Operating model: {ctx.title}", f"RACI version {v}", secs, {f"raci-v{v}": rec}, label=f"Operating model, version {v}",
                         audience="the people and teams who run the process")
    _lineage(ctx, m, kinds)
    dp = _w4.doc_problems(info)
    return {"summary": f"Version {v} is published: the matrix (Excel) and the operating model (Word, with an HTML preview) in your template" + (f"; the document check found: {dp[0]}" if dp else "") + ".",
            "counts": {"version": v, "rows": len(rows)}, "data": {"items": [{"title": f"raci-v{v}.xlsx", "detail": f"{len(rows)} activities × {len(roles)} roles"},
                                                                            {"title": f"operating-model-v{v}.docx", "detail": "the matrix, the roles and who agreed"}]}}


def _lineage(ctx: wb.Ctx, m: dict, kinds: dict) -> None:
    from .. import lineage
    pid = m.get("process_id")
    target = lineage.node_id("process", "Relay process documents", pid) if pid else None
    if not target or not db.one("SELECT 1 FROM lineage_nodes WHERE id = ?", (target,)):
        target = ctx.lineage_node("process", "Relay RACI", m["id"], label=f"RACI: {m['name']} (v{m['version']})")
    for r in m["matrix"]:
        for L in LETTERS:
            for role in split(r.get(L)):
                rn = ctx.lineage_node("role", SYSTEM, role, label=role, properties={"kind": kinds.get(role.lower()) or "person"}, own=False)
                ctx.lineage_edge(rn, target, "owns" if L == "A" else "relates", {"raci": L, "activity": r["activity"], "model": m["id"]})


def d_use(ctx: wb.Ctx) -> dict:
    m = model(ctx.get("model") or "")
    if not m:
        raise wb.StepFailed("The published model is not there any more.")
    roles = {r["role"].strip().lower(): r for r in m["roles"]}
    users = {u["email"].lower(): u for u in db.q("SELECT id, email, name FROM users WHERE active = 1")}
    db.run("DELETE FROM raci_routes WHERE model_id = ?", (m["id"],))
    rows = []
    for r in m["matrix"]:
        a = (split(r["A"]) or [""])[0]
        uids = [users[p.lower()]["id"] for p in split((roles.get(a.lower()) or {}).get("people")) if p.lower() in users]
        db.run("INSERT INTO raci_routes (model_id, process_id, activity, accountable, responsible, users, updated) VALUES (?, ?, ?, ?, ?, ?, ?)",
               (m["id"], m.get("process_id"), r["activity"], a, r["R"], json.dumps(uids), time.time()))
        rows.append([r["activity"], a, ", ".join(users[p.lower()]["name"] for p in split((roles.get(a.lower()) or {}).get("people")) if p.lower() in users) or "no Relay user (the owner decides)", r["R"]])
    owner_role = (ctx.get("process") or {}).get("owner") or max({(split(r["A"]) or [""])[0] for r in m["matrix"]}, key=lambda a: sum(1 for r in m["matrix"] if a in split(r["A"])))
    uids = [users[p.lower()]["id"] for p in split((roles.get(owner_role.lower()) or {}).get("people")) if p.lower() in users]
    db.run("INSERT INTO raci_routes (model_id, process_id, activity, accountable, responsible, users, updated) VALUES (?, ?, ?, ?, ?, ?, ?)",
           (m["id"], m.get("process_id"), PROCESS_ROW, owner_role, "", json.dumps(uids), time.time()))
    rows.insert(0, ["The process as a whole (its changes)", owner_role, ", ".join(_w4.user_name(u) for u in uids) or "no Relay user (the owner decides)", "-"])
    db.audit("raci.routes", m["id"], {"activities": len(rows), "process": m.get("process_id")}, ctx.who or ctx.owner)
    return {"summary": f"From now on Relay's approvals for this process follow the RACI: {sum(1 for x in rows if not x[2].startswith('no Relay'))} of {len(rows)} activities route to their Accountable owner "
            "(a change to the process goes to them for approval).", "counts": {"routes": len(rows)},
            "data": {"columns": ["Activity", "Accountable", "Approvals go to", "Responsible"], "rows": rows}}


# ------------------------------------------------------------------ Assess (existing RACI sheets)

def a_connect(ctx: wb.Ctx) -> dict:
    up = classify(ctx)
    n = sum(len(v) for v in up.values())
    if not n:
        raise wb.StepFailed("Upload the RACI sheets to assess (Excel or CSV: an activity column, a column per role, R / A / C / I in the cells) - and an org chart if you have one.")
    rows = [[f, "RACI sheet", f"{len(r)} row(s)"] for f, r in up["sheets"]] + [[f, "org chart", f"{len(r)} people"] for f, r in up["org"]] + [[f, "Entra ID groups", f"{len(r)} memberships"] for f, r in up["groups"]]
    return {"summary": f"{len(up['sheets'])} RACI sheet(s), {len(up['org'])} org chart(s) - read-only copies.", "counts": {"sheets": len(up["sheets"])}, "data": {"columns": ["File", "What it is", "Size"], "rows": rows}}


def a_inventory(ctx: wb.Ctx) -> dict:
    up = classify(ctx)
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs, sheets = [], {}
    for f, rows in up["sheets"]:
        roles, acts = parse_sheet(rows)
        sheets[f] = {"roles": roles, "rows": acts}
        recs.append({"id": f, "file": f, "include": True, "activities": len(acts), "roles": len(roles), "role_names": ", ".join(roles)})
    ctx.put("sheets", sheets)
    recs = [{**r, **({"include": have[r["id"]]["include"]} if r["id"] in have else {})} for r in recs]
    return {"summary": f"{len(recs)} RACI sheet(s): {sum(r['activities'] for r in recs)} activities over {len({x for s in sheets.values() for x in s['roles']})} roles.",
            "records": recs, "counts": {"sheets": len(recs)}, "data": {"columns": ["Include", "Sheet", "Activities", "Roles"], "rows": [["yes" if r["include"] else "no", r["file"], r["activities"], r["role_names"]] for r in recs]}}


def a_health(ctx: wb.Ctx) -> dict:
    sheets = ctx.get("sheets") or {}
    inc = [r["file"] for r in ctx.records("inventory") if r.get("include")]
    org_titles = {_col(r, "title", "role").lower() for _, rows in classify(ctx)["org"] for r in rows}
    checks, findings = [], []
    for f in inc:
        s = sheets.get(f) or {"roles": [], "rows": []}
        bad = [(r, conflicts(r)) for r in s["rows"]]
        bad = [(r, p) for r, p in bad if p]
        for r, p in bad:
            findings.append({"id": f"f-{_w4.slug(f)}-{r['id']}", "sheet": f, "activity": r["activity"], "issue": "; ".join(p), "severity": "high", "decision": "keep"})
        checks.append({"name": f"conflicts-{f}", "label": f"{f}: every row has one Accountable and someone Responsible", "status": "fail" if bad else "pass",
                       "measured": f"{len(s['rows']) - len(bad)} of {len(s['rows'])} rows clean", "expected": "every row", "detail": "; ".join(f"{r['activity']}: {p[0]}" for r, p in bad[:3]) or "no conflicts"})
        load = {}
        for r in s["rows"]:
            for x in split(r["R"]):
                load[x] = load.get(x, 0) + 1
        for x, n in load.items():
            if s["rows"] and n / len(s["rows"]) > 0.6 and len(s["rows"]) >= 4:
                findings.append({"id": f"f-{_w4.slug(f)}-load-{_w4.slug(x)}", "sheet": f, "activity": "-", "issue": f"{x} is Responsible for {n} of {len(s['rows'])} activities", "severity": "medium", "decision": "keep"})
        if org_titles:
            unknown = [x for x in s["roles"] if x.lower() not in org_titles and not AGENT_RE.search(x)]
            if unknown:
                findings.append({"id": f"f-{_w4.slug(f)}-roles", "sheet": f, "activity": "-", "issue": f"not in the org chart: {', '.join(unknown)}", "severity": "medium", "decision": "keep"})
    ctx.put("findings", findings)
    return {"summary": f"{len(inc)} sheet(s) checked: {sum(1 for c in checks if c['status'] == 'fail')} with conflicts; {len(findings)} finding(s).", "data": {"checks": checks},
            "counts": {"findings": len(findings)}}


def a_findings(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [{**f, **({"decision": have[f["id"]]["decision"]} if f["id"] in have else {})} for f in ctx.get("findings") or []]
    return {"summary": f"{len(recs)} finding(s) - keep what matters.", "records": recs, "counts": {"findings": len(recs)},
            "data": {"columns": ["Sheet", "Activity", "Issue", "Severity"], "rows": [[r["sheet"], r["activity"], r["issue"], r["severity"]] for r in recs]}}


FIND_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("keep", "Keep"), ("ignore", "Ignore"))), wb.Column("sheet", "Sheet", readonly=True),
                             wb.Column("activity", "Activity", readonly=True), wb.Column("issue", "Issue", readonly=True)], add=False, remove=False, label="finding")
MINUTES = {"resolve a conflict with the owners": 10, "agree a row with its owner": 3, "publish the operating model": 30}


def a_estimate(ctx: wb.Ctx) -> dict:
    from .. import registry
    sheets = ctx.get("sheets") or {}
    kept = [f for f in ctx.records("findings") if f.get("decision") != "ignore"]
    items, total = [], 0.0
    for f in [r["file"] for r in ctx.records("inventory") if r.get("include")]:
        n = len((sheets.get(f) or {}).get("rows") or [])
        k = sum(1 for x in kept if x["sheet"] == f and x["severity"] == "high")
        mins = k * MINUTES["resolve a conflict with the owners"] + n * MINUTES["agree a row with its owner"] + MINUTES["publish the operating model"]
        total += mins / 60
        items.append({"title": f, "detail": f"{k} conflict(s) to resolve, {n} row(s) to agree", "effort": f"{mins / 60:.1f} h"})
    b = registry.brand()
    rate, cur = float(b.get("hourly_rate") or 0), b.get("currency") or ""
    note = "Assumptions: " + "; ".join(f"{v} min to {k}" for k, v in MINUTES.items()) + "." + ("" if rate else " Set an hourly rate under Admin > Branding to see the cost.")
    return {"summary": f"About {total:.1f} h of the owners' time to bring {len(items)} sheet(s) to an agreed RACI" + (f" ({cur}{rate * total:,.0f})" if rate else "") + ".",
            "counts": {"hours": round(total, 1)}, "data": {"items": items, "total": f"{total:.1f} h", "note": note}}


# ------------------------------------------------------------------ Change (a published model)

def c_request(ctx: wb.Ctx) -> dict:
    m = model(ctx.scope.get("model") or "", db.user(ctx.owner or "") or {})
    if not m:
        raise wb.StepFailed("The RACI this work item changes is not one its owner can see any more.")
    ctx.put("model", m["id"])
    ctx.put("current", m["matrix"])
    ctx.put("roles_now", m["roles"])
    return {"summary": f"Change to \"{m['name']}\" version {m['version']} ({len(m['matrix'])} activities, {len(m['roles'])} roles).", "data": {"text": ctx.brief or "(no request text)"}}


def c_diagnose(ctx: wb.Ctx) -> dict:
    rows = ctx.get("current") or []
    kinds = {r["role"].strip().lower(): r["kind"] for r in ctx.get("roles_now") or []}
    def toks(s):                                           # words of four letters or more, stemmed (fixing ~ fix, suppliers ~ supplier)
        out = set()
        for x in re.findall(r"[a-z0-9]+", _w4.norm(s)):
            if len(x) >= 4:
                for suf in ("ing", "es", "s"):
                    if x.endswith(suf) and len(x) - len(suf) >= 3:
                        x = x[: -len(suf)]
                        break
                out.add(x)
        return out
    words = toks(ctx.brief)
    by_act = [r for r in rows if words & toks(r["activity"])]
    hit = by_act + [r for r in rows if r not in by_act and words & toks(" ".join(str(r.get(L) or "") for L in LETTERS))]
    checks = [{"name": f"row-{r['id']}", "label": r["activity"], "status": "fail" if conflicts(r, kinds) else "pass", "detail": "; ".join(conflicts(r, kinds)) or "clean"} for r in rows]
    return {"summary": f"The request touches {len(hit)} row(s): {', '.join(r['activity'] for r in hit[:4])}; today {sum(1 for c in checks if c['status'] == 'fail')} row(s) have a conflict.",
            "data": {"checks": checks}, "counts": {"touched": len(hit)}, "items": [r["activity"] for r in hit[:6]]}


def c_fix(ctx: wb.Ctx) -> dict:
    recs = ctx.records(ctx.step_id) or [dict(r) for r in ctx.get("current") or []]
    return {"summary": "Change the rows in place; a row with a conflict cannot be confirmed.", "records": recs, "data": _matrix_table(recs, {r["role"].strip().lower(): r["kind"] for r in ctx.get("roles_now") or []})}


def _validate_fix(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    kinds = {r["role"].strip().lower(): r["kind"] for r in ctx.get("roles_now") or []}
    out = []
    for r in recs:
        p = conflicts(r, kinds)
        r["problem"] = "; ".join(p)
        out += [f"{r.get('activity')}: {x}" for x in p]
    return out


FIX_EDIT = wb.Edit(columns=MATRIX_EDIT.columns, add=False, remove=False, validate=_validate_fix, label="row")


def c_prove(ctx: wb.Ctx) -> dict:
    after = ctx.records("fix")
    before = {r["id"]: r for r in ctx.get("current") or []}
    kinds = {r["role"].strip().lower(): r["kind"] for r in ctx.get("roles_now") or []}
    changed = [r for r in after if any(str(before.get(r["id"], {}).get(L) or "") != str(r.get(L) or "") for L in LETTERS)]
    rows = [{"name": "conflicts", "label": "No row has a conflict", "status": "fail" if any(conflicts(r, kinds) for r in after) else "pass", "measured": sum(1 for r in after if not conflicts(r, kinds)), "expected": len(after),
             "detail": "every row has one Accountable and someone Responsible; no agent Accountable"},
            {"name": "diff", "label": "What changes", "status": "pass" if changed else "warn", "measured": len(changed), "detail": ", ".join(r["activity"] for r in changed) or "nothing",
             "evidence": ctx.evidence("The changed rows", {"rows": [{"activity": r["activity"], **{f"{L} before": (before.get(r["id"]) or {}).get(L) for L in LETTERS}, **{L: r.get(L) for L in LETTERS}} for r in changed]}, kind="proof", ok=True)}]
    return {"summary": f"{len(changed)} row(s) change; " + ("no conflicts." if rows[0]["status"] == "pass" else "conflicts remain."), "data": {"checks": rows}, "counts": {"changed": len(changed)}}


def c_approve(ctx: wb.Ctx) -> dict:
    return {"summary": "Release the next version of the RACI.", "data": {"items": [{"title": r["activity"], "detail": " - ".join(f"{L}: {r.get(L) or '-'}" for L in LETTERS)} for r in ctx.records("fix")[:12]]}}


def c_learn(ctx: wb.Ctx) -> dict:
    out = d_publish(ctx, ctx.records("fix"), note=(ctx.brief or "")[:300])
    d_use(ctx)
    return out


# ------------------------------------------------------------------ the module page

def _cards(u: dict) -> list[dict]:
    rows = [[m["name"], f"v{m['version']}", len(m["matrix"]), len(m["roles"]), sum(1 for r in m["roles"] if r.get("kind") == "agent"), f"#/m/{MODULE}/i/{m['item']}" if m.get("item") else ""] for m in models(u)]
    return [{"title": "Published operating models", "columns": ["Model", "Version", "Activities", "Roles", "Agents", "Work item"], "rows": rows,
             "empty": "No RACI is published yet: a Develop item's Publish step records one."}]


wb.register(wb.Pack(
    module=MODULE,
    guide="# RACI & operating model - the work item\n\nThe RACI is drafted by rules from the process map and the org chart; people correct and agree it. No agent step.",
    lineage="each role (people, agents, systems) on the process it is Accountable for (owns) or Responsible, Consulted or Informed in (relates)",
    platforms={"files": FILES},
    schemas={"row": MATRIX_EDIT.columns, "role": ROLE_EDIT.columns},
    cards=_cards,
    work={
        "assess": wb.Work(title="Check your RACI sheets for conflicts and what it takes to agree them", steps={
            "Connect": wb.Step(kind="platform", run=a_connect, agent="Reader", text="The RACI sheets (and an org chart) are opened - read-only"),
            "Inventory": wb.Step(kind="platform", run=a_inventory, agent="Scanner", edit=wb.Edit(columns=[wb.Column("include", "Include", "bool"), wb.Column("file", "Sheet", readonly=True),
                                                                                                    wb.Column("activities", "Activities", "number", readonly=True)], add=False, remove=False, label="sheet"),
                                 text="Every sheet with its activities and roles"),
            "Health": wb.Step(kind="proof", run=a_health, view="gates", agent="Conflict checker", text="Two Accountables, nobody Responsible, an agent Accountable, overloaded roles, roles missing from the org chart"),
            "Findings": wb.Step(kind="person", run=a_findings, edit=FIND_EDIT, text="The findings - keep or ignore"),
            "Estimate": wb.Step(kind="deterministic", run=a_estimate, view="plan", agent="Estimator", text="The owners' time to agree a clean RACI, with the assumptions")}),
        "develop": wb.Work(title="From a process map and the org chart to an agreed RACI and operating model", needs_source=False, steps={
            "Processes": wb.Step(kind="deterministic", run=d_processes, agent="Reader", text="The activities of a published process (or your list), with who hands over to whom"),
            "Roles": wb.Step(kind="platform", run=d_roles, agent="Role finder", edit=ROLE_EDIT, confirm="the roles - people, agents and systems - and who is in each",
                             text="Roles from the process lanes, your org chart and Entra ID groups - agents included as roles"),
            "Draft": wb.Step(kind="deterministic", run=d_draft, agent="RACI drafter", edit=MATRIX_EDIT,
                             text="Responsible, Accountable, Consulted and Informed drafted per activity by rules; conflicts (two Accountables, no one Responsible, an agent Accountable) flagged"),
            "Agree": wb.Step(kind="deterministic", run=d_agree, agent="Sign-off clerk", edit=AGREE_EDIT, back_to="draft", text="Each Accountable owner confirms their rows (a check each in the Validation queue)"),
            "Publish": wb.Step(kind="deterministic", run=d_publish, view="plan", agent="Publisher", text="Published with the operating model (Excel and Word in your template); every version kept"),
            "Use": wb.Step(kind="deterministic", run=d_use, agent="Router", text="Approvals in Relay follow the RACI: a change to the process goes to its Accountable owner")},
            fields=[wb.Field("process", "Process", "select", options=_process_options, help="A process published by Business process documents - or upload a list of activities.")]),
        "change": wb.Work(title="Change a published RACI - no conflict gets through", needs_source=False, sources=False, steps={
            "Request": wb.Step(kind="deterministic", run=c_request, view="text", agent="Reader", text="The change in plain words and the published model"),
            "Diagnose": wb.Step(kind="proof", run=c_diagnose, view="gates", agent="Conflict checker", text="The rows the change touches and today's conflicts"),
            "Fix": wb.Step(kind="person", run=c_fix, edit=FIX_EDIT, text="You change the rows; a conflict cannot be confirmed"),
            "Prove": wb.Step(kind="proof", run=c_prove, view="gates", agent="Conflict checker", back_to="fix", text="No conflicts, and exactly what changes"),
            "Approve": wb.Step(kind="person", run=c_approve, view="plan", approver=True, text="The named approver releases the next version"),
            "Learn": wb.Step(kind="deterministic", run=c_learn, view="plan", agent="Publisher", text="The next version is published and the approvals follow it")},
            fields=[wb.Field("model", "RACI to change", "select", options=model_options, required=True)]),
    }))
