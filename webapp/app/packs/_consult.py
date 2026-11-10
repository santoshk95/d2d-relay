"""Shared helpers of the consulting packs (wave W6: delivery, assess, strategy, selection, managed, finops, enable,
architecture) — not a pack itself (the loader skips files starting with "_"; the packs import it).

Nothing invented (build-plan §2 rule 7): every number a consulting deliverable shows comes from a record the platform
holds (work items, checkpoints, Team & agents, Migrate BI, AI SDLC, the service desk, usage, the audit log, rate cards,
the library) or from a value a named person entered and confirmed in a step. Each such figure is written into the
work item's sources/<name>.json and quoted as `record:<name>#<path>`, so the P11 docs engine (the same build and
checks as `genbi deck|doc build|check`) resolves every figure and compares its value with the record: a number
without a source is a failed check, not a draft.

  facts     the platform's own records as the item's owner may see them (owner_user, work_items, migrations,
            change_requests, studio_items, rfp_items, open_checkpoints, decided_checkpoints, team_value)
  put()     a record in sources/ (returns its `record:` reference)
  say()     a sentence and its declared figures, each with its source
  deliver() a deck or a document through the docs engine: outputs (.pptx / .docx, the HTML twin, a PDF when the
            agent can draw one), the check report as evidence, a gates row with every check as a part
  sourced   a proof check: every listed number resolves to its record and agrees with it
"""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import time
from pathlib import Path

from .. import auth, checkpoints, db, registry, store
from .. import workbench as wb

DAY = 86400.0


# ------------------------------------------------------------------ numbers and words

def num(v, dp: int | None = None) -> str:
    """A number as a reader sees it (thousands separated, Western grouping so the docs checks read it back)."""
    if v is None:
        return "—"
    v = float(v)
    if dp is None:
        dp = 0 if abs(v - round(v)) < 1e-9 else 1 if abs(v * 10 - round(v * 10)) < 1e-9 else 2
    return f"{v:,.{dp}f}"


def money(v, cur: str = "") -> str:
    cur = (cur or "").strip()
    s = f"{float(v or 0):,.2f}"
    if not cur:
        return s
    return f"{cur}{s}" if cur in ("₹", "$", "€", "£") else f"{s} {cur}"


def pct(a, b, dp: int = 1) -> float | None:
    return round(100.0 * float(a) / float(b), dp) if b else None


def plural(n, word: str, many: str | None = None) -> str:
    return f"{num(n)} {word if float(n) == 1 else (many or word + 's')}"


def when(t: float | None, fmt: str = "%d %b %Y") -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime(fmt) if t else "—"


def iso_day(t: float | None) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d") if t else ""


def parse_day(s: str) -> float | None:
    """'2026-11-30' -> its UTC timestamp, else None."""
    try:
        return dt.datetime.strptime(str(s or "").strip(), "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp()
    except ValueError:
        return None


def natural(s) -> list:
    """Sort key: 'Wave 2' before 'Wave 10'."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(s or ""))]


def slug(s: str, n: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-")[:n].strip("-") or "x"


def say(tpl: str, **vals) -> tuple[str, list[dict]]:
    """A sentence whose numbers are declared figures. Values are (number, source[, dp | "money:<cur>" | "%"]) or plain
    text: say("{n} items in scope", n=(12, "record:programme#totals.records")) -> ("12 items in scope", [figure])."""
    figs, out = [], {}
    for k, v in vals.items():
        if isinstance(v, tuple):
            value, source = v[0], v[1]
            how = v[2] if len(v) > 2 else None
            if isinstance(how, str) and how.startswith("money:"):
                text = money(value, how.split(":", 1)[1])
            elif how == "%":
                text = f"{num(value, 1)} %"
            else:
                text = num(value, how if isinstance(how, int) else None)
            figs.append({"text": text, "value": float(value) if value is not None else None, "source": source})
            out[k] = text
        else:
            out[k] = v
    return tpl.format(**out), figs


def bullets(*lines: tuple[str, list[dict]]) -> tuple[list[str], list[dict]]:
    texts, figs = [], []
    for t, f in lines:
        texts.append(t)
        figs += f
    return texts, figs


# ------------------------------------------------------------------ who reads, and what they may see

def owner_user(ctx: wb.Ctx) -> dict:
    """The item's owner: records are read as the owner may see them (a scheduled round has no person behind it)."""
    return db.user(ctx.owner or "") or {}


def names() -> dict:
    return {r["id"]: r["name"] for r in db.q("SELECT id, name FROM users")}


def people(active_only: bool = True) -> list[dict]:
    return db.q("SELECT id, name, email, org_role FROM users" + (" WHERE active = 1" if active_only else "") + " ORDER BY lower(name)")


def person_options(ctx=None) -> list[tuple[str, str]]:
    return [(r["name"], r["name"]) for r in people()]


def _visible(u: dict, ids: list[str]) -> set[str]:
    return set(auth.access_map(u, ids)) if u and ids else set()


def _module_name(mid: str) -> str:
    m = registry.BY_ID.get(mid) or {}
    return m.get("short") or m.get("name") or mid


def work_items(u: dict, exclude: str | None = None, limit: int = 2000) -> list[dict]:
    """Work items of every module (the workbench's index) as this person may see them, with their journey state and
    any open decision."""
    rows = db.q("SELECT * FROM wb_items ORDER BY updated DESC LIMIT ?", (limit,))
    vis = _visible(u, [r["id"] for r in rows])
    who = names()
    out = []
    for r in rows:
        if r["id"] not in vis or (exclude and r["module"] == exclude):
            continue
        try:
            st = store.load(r["id"])
        except (KeyError, FileNotFoundError, ValueError):
            continue
        steps = st.get("steps") or []
        cur = next((s for s in steps if s["status"] not in ("done", "skipped")), None)
        waits = [c for c in db.q("SELECT id, name, created, assignee_id FROM checkpoints WHERE subject = ? AND status = 'open'", (r["id"],))]
        sent_back = db.one("SELECT COUNT(*) AS n FROM checkpoints WHERE subject = ? AND status = 'sent_back'", (r["id"],))["n"]
        gates = [g for s in steps if s.get("view") == "gates" and isinstance(s.get("data"), dict) for g in (s["data"].get("checks") or [])]
        status = "closed" if r["closed"] else r["status"]
        out.append({"ref": f"wb:{r['id']}", "id": r["id"], "kind": "Work item", "module": r["module"], "module_name": _module_name(r["module"]),
                    "work": r["work"], "work_name": wb.WORK_NAME.get(r["work"], r["work"]), "title": r["title"], "status": status,
                    "status_label": wb.STATUS_LABEL.get(status, status), "done": status in ("done", "scheduled", "closed"),
                    "attention": status in ("error", "attention"), "waiting": len(waits), "waiting_since": min((c["created"] for c in waits), default=None),
                    "waiting_for": sorted({who.get(c["assignee_id"], "—") for c in waits if c.get("assignee_id")}),
                    "steps_done": sum(1 for s in steps if s["status"] in ("done", "skipped")), "steps": len(steps),
                    "step": (cur or {}).get("name"), "sent_back": sent_back, "owner": who.get(r["owner_id"], "—"), "owner_id": r["owner_id"],
                    "parent": r.get("parent"), "created": r["created"], "updated": r["updated"],
                    "proof_pass": sum(1 for g in gates if g.get("status") == "pass"), "proof_fail": sum(1 for g in gates if g.get("status") in ("fail", "error")),
                    "link": f"#/m/{r['module']}/i/{r['id']}"})
    return out


MIGBI_DONE = ("handed", "running")


def migrations(u: dict) -> list[dict]:
    """Migrate BI programmes (P15) the person may see: objects found, reports converted and proven, waves."""
    rows = db.q("SELECT * FROM migbi_projects ORDER BY created DESC") if "migbi_projects" in db.tables() else []
    vis = _visible(u, [r["id"] for r in rows])
    who = names()
    out = []
    for r in rows:
        if r["id"] not in vis:
            continue
        reps = db.q("SELECT status, proven, wave FROM migbi_reports WHERE project = ?", (r["id"],))
        waits = db.q("SELECT id, created FROM checkpoints WHERE status = 'open' AND (subject = ? OR subject LIKE ?)", (r["id"], r["id"] + "-%"))
        out.append({"ref": f"migbi:{r['id']}", "id": r["id"], "kind": "BI migration", "module": "migbi", "module_name": "BI migration", "title": r["name"],
                    "status": r["status"], "status_label": r["status"], "done": r["status"] in MIGBI_DONE, "attention": r["status"] == "error",
                    "objects": r.get("objects") or 0, "reports": len(reps), "proven": sum(1 for x in reps if x["proven"]),
                    "waves": len({x["wave"] for x in reps if x["wave"] is not None}), "waiting": len(waits),
                    "waiting_since": min((c["created"] for c in waits), default=None), "owner": who.get(r.get("created_by"), "—"),
                    "created": r["created"], "updated": r.get("updated") or r["created"], "link": f"#/migrate-bi/{r['id']}"})
    return out


SDLC_DONE = ("released", "closed", "merged")


def change_requests(u: dict) -> list[dict]:
    """AI SDLC change requests (P16): builders and leads see them (the AI SDLC page's own rule)."""
    if not u or not auth.is_dev(u) or "sdlc_requests" not in db.tables():
        return []
    who = names()
    out = []
    for r in db.q("SELECT * FROM sdlc_requests ORDER BY updated DESC LIMIT 500"):
        waits = db.q("SELECT id, created FROM checkpoints WHERE status = 'open' AND subject = ?", (r["id"],))
        out.append({"ref": f"sdlc:{r['id']}", "id": r["id"], "kind": "Change request", "module": "sdlc", "module_name": "AI SDLC", "title": r["title"],
                    "status": r["status"], "status_label": r["status"].replace("_", " "), "done": r["status"] in SDLC_DONE or bool(r.get("closed")),
                    "attention": r["status"] in ("error", "blocked"), "stage": r.get("stage"), "waiting": len(waits),
                    "waiting_since": min((c["created"] for c in waits), default=None), "owner": who.get(r.get("owner_id"), "—"),
                    "created": r["created"], "updated": r["updated"], "link": f"#/sdlc/{r['id']}"})
    return out


def _kind_items(u: dict, kind: str) -> list[dict]:
    ps = [p for p in store.all_projects() if p.get("kind") == kind]
    vis = _visible(u, [p["id"] for p in ps])
    return [p for p in ps if p["id"] in vis]


def studio_items(u: dict) -> list[dict]:
    out = []
    for p in _kind_items(u, "deliverable"):
        try:
            st = store.load(p["id"])
        except (KeyError, FileNotFoundError, ValueError):
            continue
        out.append({"ref": f"studio:{p['id']}", "id": p["id"], "kind": "Deliverable", "module": "proposals", "module_name": _module_name("proposals"),
                    "title": st.get("name") or p["id"], "status": st.get("status"), "status_label": str(st.get("status") or "").replace("_", " "),
                    "done": st.get("status") == "final", "attention": st.get("status") == "error",
                    "waiting": 1 if st.get("status") in ("awaiting_outline", "awaiting_review") else 0, "waiting_since": st.get("updated") if st.get("status") in ("awaiting_outline", "awaiting_review") else None,
                    "owner": names().get((db.project(p["id"]) or {}).get("owner_id"), "—"), "created": st.get("created"), "updated": st.get("updated"), "link": f"#/studio/{p['id']}"})
    return out


def rfp_items(u: dict) -> list[dict]:
    out = []
    for p in _kind_items(u, "rfp"):
        try:
            st = store.load(p["id"])
        except (KeyError, FileNotFoundError, ValueError):
            continue
        s = st.get("status")
        out.append({"ref": f"rfp:{p['id']}", "id": p["id"], "kind": "RFP response", "module": "rfp", "module_name": _module_name("rfp"), "title": st.get("name") or p["id"],
                    "status": s, "status_label": str(s or "").replace("_", " "), "done": s in ("submitted", "won", "lost", "withdrawn", "no_go"),
                    "attention": s == "error", "waiting": 1 if str(s or "").startswith("awaiting") else 0, "waiting_since": st.get("updated") if str(s or "").startswith("awaiting") else None,
                    "owner": names().get((db.project(p["id"]) or {}).get("owner_id"), "—"), "created": st.get("created"), "updated": st.get("updated"), "link": f"#/rfp/{p['id']}"})
    return out


def every_record(u: dict, exclude: str | None = None) -> list[dict]:
    """Everything a programme can track: work items of every module, BI migrations, change requests, studio
    deliverables and RFP responses."""
    return work_items(u, exclude=exclude) + migrations(u) + change_requests(u) + studio_items(u) + rfp_items(u)


def open_checkpoints(u: dict) -> list[dict]:
    out = []
    for r in db.q("SELECT * FROM checkpoints WHERE status = 'open' ORDER BY created"):
        c = checkpoints._public(r)
        if u and checkpoints.visible(u, c):
            out.append(c)
    return out


def decided_checkpoints(u: dict, since: float) -> list[dict]:
    rows = [checkpoints._public(r) for r in db.q("SELECT * FROM checkpoints WHERE decided >= ? AND status IN ('accepted', 'sent_back')", (since,))]
    if auth.is_admin(u):
        return rows
    teams = {t["id"] for t in u.get("teams") or []}
    return [c for c in rows if c.get("decided_by") == u.get("id") or c.get("assignee_id") == u.get("id") or c.get("team_id") in teams or c.get("opened_by") == u.get("id")]


def team_value(u: dict, period: str = "7d") -> dict:
    """Team & agents' own figures for the period (agent hours, people's hours deciding, right first time, AI cost)."""
    from .. import team
    try:
        t = team.build(u, period)
    except Exception:  # noqa: BLE001 - Team & agents is optional here: its figures are left out, never guessed
        return {}
    k = t.get("kpis") or {}
    return {"period": period, "agent_hours": k.get("agent_hours") or 0, "people_hours": k.get("people_hours") or 0, "decided": k.get("decided") or 0,
            "accepted": k.get("accepted") or 0, "rft_pct": k.get("rft"), "waiting": k.get("waiting") or 0, "ai_cost_usd": k.get("ai_cost_usd") or 0,
            "agents": [{"agent": a["agent"], "runs": a["runs"], "hours": a["hours"]} for a in (t.get("agents") or [])[:12]]}


# ------------------------------------------------------------------ sources/: the records a deliverable quotes

def put(ctx: wb.Ctx, name: str, data) -> str:
    """Write sources/<name>.json in the item's folder (what `record:<name>#…` resolves to); returns the reference."""
    d = ctx.dir / "sources"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return f"record:{name}"


def read(ctx: wb.Ctx, name: str, default=None):
    p = ctx.dir / "sources" / f"{name}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def resolver(ctx: wb.Ctx):
    from genbi_kit.docs.sources import Resolver
    return Resolver(ctx.dir, store.root())


@wb.proof("sourced", "Every number has a source")
def _p_sourced(ctx: wb.Ctx, figures: list[dict], **_):
    """figures: [{"label", "value", "source"}] — each source must resolve inside the item's folder and, when it names a
    number, agree with the value (half a unit or 0.5 %, the docs engine's tolerance)."""
    res = resolver(ctx)
    rows, bad = [], 0
    for f in figures:
        src = str(f.get("source") or "")
        r = res.resolve(src) if src else {"ok": False, "why": "no source given", "value": None}
        ok = bool(r["ok"])
        why = r.get("why") or ""
        v = f.get("value")
        if ok and r.get("value") is not None and v is not None:
            try:
                ok = abs(float(v) - float(r["value"])) <= max(0.5, abs(float(r["value"])) * 0.005)
                why = "" if ok else f"says {float(v):g} but the record holds {float(r['value']):g}"
            except (TypeError, ValueError):
                ok, why = False, "not a number"
        bad += 0 if ok else 1
        rows.append({"figure": f.get("label") or src, "value": v, "source": src or "(none)", "resolves": ok, "why": why})
    return {"status": "pass" if figures and not bad else "fail" if bad else "skip", "measured": len(figures) - bad, "expected": len(figures), "rows": rows,
            "detail": (f"every one of {len(figures)} number(s) resolves to its record" if not bad else
                       f"{bad} of {len(figures)} number(s) have no source or disagree with it: " + "; ".join(f"{x['figure']} ({x['why']})" for x in rows if not x["resolves"])[:400])}


# ------------------------------------------------------------------ deliverables through the P11 docs engine

def template_options(u=None) -> list[tuple[str, str]]:
    tpl = registry.templates()
    out = [("relay", "The RELAY template")]
    if tpl.get("pptx") or tpl.get("docx"):
        out.append(("tenant", "This workspace's template (Admin › Branding)"))
    return out


def deliver(ctx: wb.Ctx, name: str, spec: dict, label: str) -> dict:
    """Build a deck or a document from `spec` (deck.yaml / doc.yaml as a dict, every figure sourced) with the P11
    engine — the build and checks of `genbi deck|doc build|check` — into deliverables/<name>/. The .pptx / .docx, the
    HTML twin and a PDF (when the agent's Chromium can draw it) go to the outputs; the check report is evidence."""
    import yaml
    from genbi_kit.docs import build as docs_build
    from genbi_kit.docs import checks as docs_checks

    from .. import studio
    d = ctx.dir
    choice = ctx.scope.get("template") if ctx.scope.get("template") in ("relay", "tenant") else "relay"
    if choice == "tenant" and not any(registry.templates().get(k) for k in ("pptx", "docx")):
        choice = "relay"
    studio.write_brand(d, choice)
    spec = {**spec, "template": choice}
    path = d / f"{name}.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")
    out = d / "deliverables" / name
    shutil.rmtree(out, ignore_errors=True)
    info = docs_build.build(path, out, workspace=store.root(), renderer=studio._renderer, evidence_base=f"#/m/{ctx.module}/i/{ctx.id}?ref=", name=name, pdf=True)
    rep = info["report"]
    files = []
    for k in ("pptx", "docx", "pdf"):
        f = info["files"].get(k)
        if f and (out / f).exists():
            files.append(ctx.output(f, (out / f).read_bytes(), label=f"{label} ({k.upper()})"))
    if info["files"].get("twin") and (out / "twin.html").exists():
        files.append(ctx.output(f"{name}-preview.html", (out / "twin.html").read_bytes(), label=f"{label} (HTML preview)"))
    ctx.output(f"{name}.yaml", path.read_bytes(), label=f"{label} (YAML: what was built)")
    ev = ctx.evidence(f"Document checks: {label}", {"checks": rep["checks"], "counts": rep["counts"], "template": rep.get("template"), "kind": rep.get("kind")},
                      kind="docs-check", ok=rep["ok"])
    probs = docs_checks.problems(rep)
    made = info.get("deck") or info.get("doc") or {}
    gate = {"name": f"docs:{name}", "label": f"{label}: the document engine's checks", "status": "pass" if rep["ok"] else "fail",
            "measured": f"{rep['counts']['fails']} problem(s), {rep['counts']['warnings']} warning(s)", "expected": "no problems",
            "detail": ("; ".join(probs[:4]) if probs else f"{rep['counts']['figures']} figure(s), {rep['counts']['refs']} source reference(s) — sources resolve, numbers agree, "
                       "no placeholder text, alt text, contrast, house style, nothing from outside this workspace's folder"),
            "evidence": ev, "parts": [{"label": c["label"], "status": c["status"], "detail": c["summary"]} for c in rep["checks"]]}
    return {"ok": rep["ok"], "gate": gate, "files": files, "report": rep, "kind": rep.get("kind"),
            "units": made.get("slides") or made.get("blocks"), "problems": probs}


def check_spec(ctx: wb.Ctx, name: str) -> dict:
    """`genbi deck|doc check` on a deliverable's YAML in the item's folder (the same report the build made)."""
    from genbi_kit.docs import build as docs_build
    return docs_build.check(ctx.dir / f"{name}.yaml", workspace=store.root())


def table(columns: list[str], rows: list[list], source: str, caption: str) -> dict:
    return {"columns": columns, "rows": [[("—" if c is None or c == "" else str(c)) for c in r] for r in rows], "source": source, "caption": caption}


def chunks(rows: list, n: int = 14) -> list[list]:
    return [rows[i:i + n] for i in range(0, len(rows), n)] or [[]]


def brand_line() -> str:
    b = registry.brand()
    return b["full"] + (f" · {b['powered']}" if b.get("partner") else "")


# ------------------------------------------------------------------ records a person keeps between steps

def keep_edits(ctx: wb.Ctx, fresh: list[dict], keys: tuple) -> list[dict]:
    """A step that runs again keeps what a person changed: rows with the same id keep the edited keys, rows a person
    added stay, new suggestions are appended."""
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    out, seen = [], set()
    for r in fresh:
        old = have.get(r["id"])
        out.append({**r, **({k: old[k] for k in keys if k in old} if old else {})})
        seen.add(r["id"])
    out += [r for rid, r in have.items() if rid not in seen and r.get("origin") == "person"]
    return out


def need(cond: bool, msg: str) -> None:
    if not cond:
        raise wb.StepFailed(msg)


def now() -> float:
    return time.time()


def lc(s: str) -> str:
    return s[:1].lower() + s[1:]


def folder(ctx: wb.Ctx) -> Path:
    return ctx.dir
