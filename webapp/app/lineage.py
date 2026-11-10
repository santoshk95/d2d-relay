"""The lineage & asset graph (build-plan v2, P13): one graph of tables, columns, jobs, flows, bots, reports, pages,
measures, APIs, file drops, queues, systems and owners, shared by the Knowledge map, Lineage, Integration analytics,
Data observability, Migrate and the studio's diagrams.

It extends phase 4's organisation ontology rather than starting a second graph: the entities, their key mappings
(source, table, column) and relations are loaded in as nodes and edges, and so is every dashboard's definition
(source files and warehouse objects -> model tables and columns -> measures -> pages -> report), so today's data
appears on the map before any discovery adapter runs. Other modules (Integration analytics first) add their own
nodes and edges through `upsert_node` / `upsert_edge`, keyed by (kind, system, name) so a re-scan never duplicates.

Edges are stored in the direction the data flows (from = upstream, to = downstream); `contains` is the one
structural edge (parent -> child) and is walked the other way round for impact, because a change in a page or a
measure changes the report that holds it.
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import auth, db, store

router = APIRouter()

db.register_schema("""
CREATE TABLE IF NOT EXISTS lineage_nodes (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, system TEXT NOT NULL DEFAULT '', name TEXT NOT NULL, label TEXT,
  properties TEXT NOT NULL DEFAULT '{}', source TEXT, status TEXT, owner TEXT, first_seen REAL NOT NULL, last_seen REAL NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS lineage_nodes_key ON lineage_nodes (kind, system, name);
CREATE INDEX IF NOT EXISTS lineage_nodes_kind ON lineage_nodes (kind);
CREATE TABLE IF NOT EXISTS lineage_edges (
  from_id TEXT NOT NULL, to_id TEXT NOT NULL, kind TEXT NOT NULL, evidence TEXT NOT NULL DEFAULT '{}', source TEXT,
  first_seen REAL NOT NULL, last_seen REAL NOT NULL, PRIMARY KEY (from_id, to_id, kind));
CREATE INDEX IF NOT EXISTS lineage_edges_to ON lineage_edges (to_id);
""")

NODE_KINDS = ("table", "column", "job", "flow", "bot", "report", "page", "measure", "api", "file_drop", "queue", "system", "owner", "entity")
EDGE_KINDS = ("reads", "writes", "feeds", "calls", "owns", "contains", "schedules", "identifies", "relates")
KIND_LABEL = {"table": "Table", "column": "Column", "job": "Job", "flow": "Flow", "bot": "Bot", "report": "Report", "page": "Page",
              "measure": "Measure", "api": "API", "file_drop": "File drop", "queue": "Queue", "system": "System", "owner": "Owner", "entity": "Entity"}
SYNC_AGE_S = 300                      # the dashboards and the ontology are re-read at most this often, on demand
_COL_REF = re.compile(r"('[^']+'|[A-Za-z_][\w ]*?)\[([^\]]+)\]")
_MEASURE_REF = re.compile(r"\[([^\]]+)\]")


def node_id(kind: str, system: str, name: str) -> str:
    return "n-" + hashlib.sha1(f"{kind}|{system or ''}|{name}".encode("utf-8")).hexdigest()[:14]


def _j(s: str | None) -> dict:
    try:
        return json.loads(s or "{}")
    except ValueError:
        return {}


def _public(r: dict) -> dict:
    out = dict(r)
    out["properties"] = _j(r.get("properties"))
    out["label"] = r.get("label") or r["name"]
    out["kind_label"] = KIND_LABEL.get(r["kind"], r["kind"])
    return out


# ------------------------------------------------------------------ writing (idempotent)

def upsert_node(kind: str, system: str, name: str, *, label: str | None = None, properties: dict | None = None,
                source: str | None = None, status: str | None = None, owner: str | None = None, now: float | None = None) -> str:
    """Create or refresh a node; the key is (kind, system, name). Properties merge, first_seen is kept."""
    if kind not in NODE_KINDS:
        raise ValueError(f"Unknown node kind {kind!r}")
    name = str(name).strip()[:300]
    system = str(system or "").strip()[:200]
    nid, now = node_id(kind, system, name), now or time.time()
    have = db.one("SELECT id, properties FROM lineage_nodes WHERE id = ?", (nid,))
    if have:
        props = {**_j(have["properties"]), **(properties or {})}
        db.run("UPDATE lineage_nodes SET label = COALESCE(?, label), properties = ?, source = COALESCE(?, source), status = COALESCE(?, status), "
               "owner = COALESCE(?, owner), last_seen = ? WHERE id = ?", (label, json.dumps(props), source, status, owner, now, nid))
    else:
        db.run("INSERT INTO lineage_nodes (id, kind, system, name, label, properties, source, status, owner, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
               (nid, kind, system, name, label, json.dumps(properties or {}), source, status, owner, now, now))
    return nid


def upsert_edge(from_id: str, to_id: str, kind: str, evidence: dict | None = None, source: str | None = None, now: float | None = None) -> None:
    if kind not in EDGE_KINDS:
        raise ValueError(f"Unknown edge kind {kind!r}")
    if from_id == to_id:
        return
    now = now or time.time()
    have = db.one("SELECT evidence FROM lineage_edges WHERE from_id = ? AND to_id = ? AND kind = ?", (from_id, to_id, kind))
    if have:
        ev = {**_j(have["evidence"]), **(evidence or {})}
        db.run("UPDATE lineage_edges SET evidence = ?, source = COALESCE(?, source), last_seen = ? WHERE from_id = ? AND to_id = ? AND kind = ?",
               (json.dumps(ev), source, now, from_id, to_id, kind))
    else:
        db.run("INSERT INTO lineage_edges (from_id, to_id, kind, evidence, source, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?)",
               (from_id, to_id, kind, json.dumps(evidence or {}), source, now, now))


def prune(source: str, before: float) -> dict:
    """What a source stopped reporting disappears: its edges and its own nodes not seen since `before`."""
    gone = [r["id"] for r in db.q("SELECT id FROM lineage_nodes WHERE source = ? AND last_seen < ?", (source, before))]
    edges = db.run("DELETE FROM lineage_edges WHERE source = ? AND last_seen < ?", (source, before))
    for nid in gone:
        db.run("DELETE FROM lineage_edges WHERE from_id = ? OR to_id = ?", (nid, nid))
        db.run("DELETE FROM lineage_nodes WHERE id = ?", (nid,))
    return {"nodes": len(gone), "edges": edges}


def source_table(src: str, now: float | None = None, source: str = "dashboards") -> str:
    """The table node for a semantic-layer source key: 'snowflake:SCHEMA.OBJECT' (a warehouse object) or
    '<project>/<file>' (an upload). The same key is what the ontology's key mappings use."""
    if "/" in src and (":" not in src or src.index("/") < src.index(":")):
        pid, f = src.split("/", 1)
        return upsert_node("table", pid, f, label=f"{f} (upload)", properties={"source_key": src, "upload": True, "project": pid}, source=source, now=now)
    kind, obj = src.split(":", 1) if ":" in src else ("file", src)
    return upsert_node("table", kind, obj, label=f"{obj} ({kind})", properties={"source_key": src, "warehouse": kind}, source=source, now=now)


# ------------------------------------------------------------------ loading today's data

def sync_semantic(now: float | None = None) -> dict:
    """Phase 4's ontology: entities, the columns that identify them in each source, and their relations."""
    from . import semantic
    now = now or time.time()
    ont = semantic.ontology()
    n = 0
    for e in ont["entities"]:
        eid = upsert_node("entity", "ontology", e["name"], label=e["name"], source="ontology", status=e.get("status"), owner=e.get("owner_team"), now=now,
                          properties={"entity_id": e["id"], "definition": (e.get("definition") or e.get("description") or "")[:300], "synonyms": e.get("synonyms") or []})
        n += 1
        for k in e.get("keys") or []:
            col = upsert_node("column", k["source"], k["col"], label=f"{k['tbl']}.{k['col']}", properties={"table": k["tbl"], "source_key": k["source"]}, source="ontology", now=now)
            upsert_edge(source_table(k["source"], now, "ontology"), col, "contains", {"table": k["tbl"]}, "ontology", now)
            upsert_edge(col, eid, "identifies", {"table": k["tbl"]}, "ontology", now)
    by_id = {e["id"]: e["name"] for e in ont["entities"]}
    for r in ont["relations"]:
        if r["from_id"] in by_id and r["to_id"] in by_id:
            upsert_edge(node_id("entity", "ontology", by_id[r["from_id"]]), node_id("entity", "ontology", by_id[r["to_id"]]), "relates", {"verb": r["verb"]}, "ontology", now)
    return {"entities": n, **prune("ontology", now)}


def _definition_path(pid: str, st: dict):
    d = store.project_dir(pid)
    versions = [v.get("v") for v in st.get("versions") or [] if v.get("v")]
    v = None
    if st.get("output"):
        v = ((st.get("publishes") or [{}])[-1].get("v")) or st.get("approved")
    if not v and versions:
        v = versions[-1]
    if v and (d / "versions" / f"v{v}" / "definition.yaml").exists():
        return d / "versions" / f"v{v}" / "definition.yaml", v
    if (d / "definition.yaml").exists():
        return d / "definition.yaml", None
    return None, None


def _refs(text: str) -> tuple[set[tuple[str, str]], set[str]]:
    """Column references Table[Column] and measure references [Measure] in DAX or a visual's field list."""
    cols = {(t.strip("'"), c) for t, c in _COL_REF.findall(text)}
    rest = _COL_REF.sub(" ", text)
    return cols, set(_MEASURE_REF.findall(rest))


def _strings(obj) -> list[str]:
    """Every string inside a visual's fields (nested dicts and lists), one per line for _refs."""
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _strings(v)]
    if isinstance(obj, (list, tuple)):
        return [s for v in obj for s in _strings(v)]
    return []


def sync_dashboards(now: float | None = None) -> dict:
    """Every dashboard's published definition: sources -> model tables and columns -> measures -> pages -> report."""
    from genbi_kit import definition
    from . import semantic
    now = now or time.time()
    reports = 0
    for p in store.all_projects():
        try:
            st = store.load(p["id"])
        except (KeyError, FileNotFoundError, ValueError):
            continue
        if st.get("kind") and st.get("kind") != "dashboard":
            continue
        path, v = _definition_path(p["id"], st)
        if not path:
            continue
        try:
            dd = definition.load(path)
        except Exception:  # noqa: BLE001 - an unreadable definition is not on the map
            continue
        pid, name = p["id"], p.get("name") or p["id"]
        model = f"model:{pid}"
        report = upsert_node("report", "Power BI", name, label=name, source="dashboards", status="published" if st.get("output") else (st.get("status") or "draft"), now=now,
                             properties={"project": pid, "version": v, "link": f"#/p/{pid}", "pages": len(dd.get("pages") or []), "measures": len(dd.get("measures") or [])})
        reports += 1
        try:
            sources, _ = semantic._sources_of(pid)
        except Exception:  # noqa: BLE001
            sources = {}
        try:                                                        # an extract not pulled yet is still a warehouse object
            from . import connectors
            for f, m in connectors.manifest(store.project_dir(pid)).items():
                if m.get("kind") and m.get("object"):
                    sources.setdefault(f, f"{m['kind']}:{m['object']}")
        except Exception:  # noqa: BLE001
            pass
        tables: dict[str, str] = {}
        for t in dd.get("tables") or []:
            tname = t.get("name")
            if not tname:
                continue
            file = t.get("csv") or t.get("extract") or t.get("file")
            tid = upsert_node("table", model, tname, label=f"{tname} ({name} model)", source="dashboards", now=now,
                              properties={"project": pid, "report": name, "columns": len(t.get("columns") or []), "from": file, "description": (t.get("description") or "")[:200]})
            tables[tname] = tid
            upsert_edge(report, tid, "contains", {}, "dashboards", now)
            if file:
                src = sources.get(file) or f"{pid}/{file}"
                sid = source_table(src, now)
                upsert_edge(sid, tid, "feeds", {"file": file}, "dashboards", now)
                for c in t.get("columns") or []:
                    cname = c.get("name")
                    if not cname:
                        continue
                    scol = upsert_node("column", src, c.get("source") or cname, label=f"{file}.{c.get('source') or cname}", properties={"source_key": src}, source="dashboards", now=now)
                    upsert_edge(sid, scol, "contains", {}, "dashboards", now)
                    mcol = upsert_node("column", model, f"{tname}.{cname}", label=f"{tname}[{cname}]", properties={"project": pid, "type": c.get("type")}, source="dashboards", now=now)
                    upsert_edge(tid, mcol, "contains", {}, "dashboards", now)
                    upsert_edge(scol, mcol, "feeds", {}, "dashboards", now)
            else:
                for c in t.get("columns") or []:
                    if c.get("name"):
                        mcol = upsert_node("column", model, f"{tname}.{c['name']}", label=f"{tname}[{c['name']}]", properties={"project": pid, "type": c.get("type")}, source="dashboards", now=now)
                        upsert_edge(tid, mcol, "contains", {}, "dashboards", now)
        for rel in dd.get("relationships") or []:
            m = re.match(r"\s*('?[^'\[]+'?)\[([^\]]+)\]\s*->\s*('?[^'\[]+'?)\[([^\]]+)\]", str(rel))
            if m and m.group(1).strip("'") in tables and m.group(3).strip("'") in tables:
                upsert_edge(tables[m.group(1).strip("'")], tables[m.group(3).strip("'")], "relates", {"from": f"{m.group(1)}[{m.group(2)}]", "to": f"{m.group(3)}[{m.group(4)}]"}, "dashboards", now)
        measures: dict[str, str] = {}
        for mdef in dd.get("measures") or []:
            mname = mdef.get("name")
            if not mname:
                continue
            measures[mname] = upsert_node("measure", model, mname, label=mname, source="dashboards", now=now,
                                          properties={"project": pid, "report": name, "format": mdef.get("format"), "folder": mdef.get("folder"), "expression": str(mdef.get("expression") or "")[:300], "description": (mdef.get("description") or "")[:200]})
            upsert_edge(report, measures[mname], "contains", {}, "dashboards", now)
        for mdef in dd.get("measures") or []:
            mname = mdef.get("name")
            if not mname:
                continue
            cols, refs = _refs(str(mdef.get("expression") or ""))
            for t, c in cols:
                if t in tables:
                    upsert_edge(node_id("column", model, f"{t}.{c}"), measures[mname], "reads", {}, "dashboards", now)
            for r in refs:
                if r in measures and r != mname:
                    upsert_edge(measures[r], measures[mname], "reads", {}, "dashboards", now)
        for pg in dd.get("pages") or []:
            pname = pg.get("name")
            if not pname:
                continue
            visuals = [vz for row in pg.get("rows") or [] for vz in row.get("visuals") or []] + list(pg.get("visuals") or [])
            pgid = upsert_node("page", model, pname, label=f"{pname} (page)", source="dashboards", now=now, properties={"project": pid, "report": name, "visuals": len(visuals)})
            upsert_edge(report, pgid, "contains", {}, "dashboards", now)
            cols, refs = _refs("\n".join(_strings([vz.get("fields") or {} for vz in visuals] + [vz.get("title") for vz in visuals if isinstance(vz.get("title"), str)])))
            for t, c in cols:
                if t in tables:
                    upsert_edge(node_id("column", model, f"{t}.{c}"), pgid, "reads", {}, "dashboards", now)
            for r in refs:
                if r in measures:
                    upsert_edge(measures[r], pgid, "reads", {}, "dashboards", now)
    return {"reports": reports, **prune("dashboards", now)}


def sync_all(who: str | None = None) -> dict:
    now = time.time()
    out = {"ontology": sync_semantic(now), "dashboards": sync_dashboards(now), "at": now}
    db.set_meta("lineage_synced", str(now))
    db.audit("lineage.sync", None, {k: v for k, v in out.items() if k != "at"}, who or "system")
    return out


def ensure_synced(max_age: float = SYNC_AGE_S) -> None:
    last = float(db.meta("lineage_synced", "0") or 0)
    if time.time() - last > max_age:
        sync_all()


# ------------------------------------------------------------------ reading

def _edges() -> list[dict]:
    return db.q("SELECT from_id, to_id, kind, evidence, source FROM lineage_edges")


def _flow(e: dict) -> tuple[str, str]:
    """(upstream, downstream) of an edge: a parent is downstream of what it contains."""
    return (e["to_id"], e["from_id"]) if e["kind"] == "contains" else (e["from_id"], e["to_id"])


def _adjacency(edges: list[dict]) -> tuple[dict, dict]:
    down: dict[str, list] = collections.defaultdict(list)
    up: dict[str, list] = collections.defaultdict(list)
    for e in edges:
        a, b = _flow(e)
        down[a].append((b, e))
        up[b].append((a, e))
    return up, down


def _nodes(ids: list[str]) -> dict[str, dict]:
    out = {}
    ids = list(ids)
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        for r in db.q(f"SELECT * FROM lineage_nodes WHERE id IN ({','.join('?' * len(chunk))})", tuple(chunk)):
            out[r["id"]] = _public(r)
    return out


def get(nid: str) -> dict | None:
    r = db.one("SELECT * FROM lineage_nodes WHERE id = ?", (nid,))
    return _public(r) if r else None


def _walk(start: str, adj: dict, depth: int | None, stop_at: set[str] | None = None, kinds_of: dict | None = None) -> dict[str, int]:
    """Nodes reachable from start along adj, with their hop count; a node whose kind is in stop_at is reached but not
    walked through (systems are hubs: everything would be downstream of everything)."""
    seen, frontier = {start: 0}, [start]
    while frontier:
        nxt = []
        for a in frontier:
            hop = seen[a] + 1
            if depth is not None and hop > depth:
                continue
            if stop_at and a != start and kinds_of and kinds_of.get(a) in stop_at:
                continue
            for b, _ in adj.get(a, []):
                if b in seen:
                    continue
                seen[b] = hop
                nxt.append(b)
        frontier = nxt
    seen.pop(start, None)
    return seen


def slice(nid: str, depth: int = 2, direction: str = "both", kinds: list[str] | None = None) -> dict:  # noqa: A001
    """The neighbourhood of a node: upstream and downstream to N hops, with the edges between them."""
    focus = get(nid)
    if not focus:
        raise HTTPException(404, "No such item on the map.")
    edges = _edges()
    up, down = _adjacency(edges)
    depth = max(1, min(int(depth or 1), 6))
    ups = _walk(nid, up, depth) if direction in ("both", "up") else {}
    downs = _walk(nid, down, depth) if direction in ("both", "down") else {}
    ids = {nid} | set(ups) | set(downs)
    found = _nodes(list(ids))
    want = set(kinds) if kinds else None
    out_nodes = []
    for i, n in found.items():
        if want and i != nid and n["kind"] not in want:
            continue
        role = "focus" if i == nid else "up" if i in ups and i not in downs else "down" if i in downs and i not in ups else "both"
        out_nodes.append({**n, "role": role, "hop": 0 if i == nid else min(ups.get(i, 99), downs.get(i, 99)) * (-1 if role == "up" else 1)})
    keep = {n["id"] for n in out_nodes}
    out_edges = [{"from": e["from_id"], "to": e["to_id"], "kind": e["kind"], "evidence": _j(e["evidence"]), "source": e["source"]} for e in edges if e["from_id"] in keep and e["to_id"] in keep]
    total = db.one("SELECT COUNT(*) AS n FROM lineage_nodes")["n"]
    return {"focus": nid, "depth": depth, "direction": direction, "nodes": out_nodes, "edges": out_edges,
            "counts": {"nodes": len(out_nodes), "edges": len(out_edges), "nodes_total": total, "edges_total": len(edges), "upstream": len(ups), "downstream": len(downs)}}


def impact(nid: str, stop_at: set[str] | None = None) -> dict:
    """If this changes: everything downstream (any distance), by kind, and the names that matter most. With
    stop_at={"system"} the walk does not continue through system hubs (what an integration feeds directly)."""
    focus = get(nid)
    if not focus:
        raise HTTPException(404, "No such item on the map.")
    _, down = _adjacency(_edges())
    kinds_of = {r["id"]: r["kind"] for r in db.q("SELECT id, kind FROM lineage_nodes")} if stop_at else None
    hops = _walk(nid, down, None, stop_at, kinds_of)
    found = _nodes(list(hops))
    by_kind = collections.Counter(n["kind"] for n in found.values())
    top = sorted(found.values(), key=lambda n: (hops[n["id"]], n["kind"] != "report", n["label"]))
    return {"id": nid, "name": focus["label"], "downstream": len(found), "by_kind": dict(by_kind),
            "reports": [n["label"] for n in top if n["kind"] == "report"][:20],
            "items": [{"id": n["id"], "label": n["label"], "kind": n["kind"], "hop": hops[n["id"]], "status": n.get("status")} for n in top[:40]],
            "text": "Nothing downstream." if not found else "If this changes: " + ", ".join(f"{v} {KIND_LABEL.get(k, k).lower()}{'s' if v != 1 and not KIND_LABEL.get(k, k).endswith('s') else ''}" for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1])) + "."}


def neighbours(nid: str) -> dict:
    up, down = _adjacency(_edges())
    ups = _nodes([a for a, _ in up.get(nid, [])])
    downs = _nodes([b for b, _ in down.get(nid, [])])
    return {"upstream": [{**n, "edge": next(e["kind"] for a, e in up[nid] if a == n["id"])} for n in ups.values()],
            "downstream": [{**n, "edge": next(e["kind"] for b, e in down[nid] if b == n["id"])} for n in downs.values()]}


def search(q: str, kinds: list[str] | None = None, limit: int = 30) -> list[dict]:
    q = (q or "").strip().lower()
    if not q:
        return []
    rows = db.q("SELECT * FROM lineage_nodes WHERE (lower(name) LIKE ? OR lower(label) LIKE ? OR lower(system) LIKE ?) ORDER BY length(name) LIMIT ?",
                (f"%{q}%", f"%{q}%", f"%{q}%", 400))
    want = set(kinds) if kinds else None
    out = [_public(r) for r in rows if not want or r["kind"] in want]
    out.sort(key=lambda n: (0 if n["label"].lower().startswith(q) else 1 if q in n["label"].lower() else 2, len(n["label"])))
    return out[:limit]


def path(a: str, b: str) -> dict:
    """The shortest connection between two items, whichever way the data flows."""
    if not get(a) or not get(b):
        raise HTTPException(404, "No such item on the map.")
    edges = _edges()
    adj: dict[str, list] = collections.defaultdict(list)
    for e in edges:
        adj[e["from_id"]].append((e["to_id"], e))
        adj[e["to_id"]].append((e["from_id"], e))
    prev: dict[str, tuple] = {a: (None, None)}
    frontier = [a]
    while frontier and b not in prev:
        nxt = []
        for x in frontier:
            for y, e in adj[x]:
                if y not in prev:
                    prev[y] = (x, e)
                    nxt.append(y)
        frontier = nxt
    if b not in prev:
        return {"found": False, "nodes": [], "edges": []}
    ids, es, cur = [b], [], b
    while prev[cur][0] is not None:
        es.append(prev[cur][1])
        cur = prev[cur][0]
        ids.append(cur)
    ids.reverse(); es.reverse()
    found = _nodes(ids)
    return {"found": True, "nodes": [{**found[i], "role": "focus" if i in (a, b) else "both", "hop": k} for k, i in enumerate(ids) if i in found],
            "edges": [{"from": e["from_id"], "to": e["to_id"], "kind": e["kind"], "evidence": _j(e["evidence"])} for e in es]}


def whole(limit: int = 250, kinds: list[str] | None = None) -> dict:
    """The busiest part of the whole map (by connections), for the "whole estate" view."""
    edges = _edges()
    deg: collections.Counter = collections.Counter()
    for e in edges:
        deg[e["from_id"]] += 1; deg[e["to_id"]] += 1
    rows = db.q("SELECT * FROM lineage_nodes" + (f" WHERE kind IN ({','.join('?' * len(kinds))})" if kinds else ""), tuple(kinds or ()))
    rows.sort(key=lambda r: (-deg[r["id"]], r["kind"], r["name"]))
    keep = {r["id"] for r in rows[:limit]}
    nodes = [{**_public(r), "role": "both", "hop": 0} for r in rows[:limit]]
    return {"nodes": nodes, "edges": [{"from": e["from_id"], "to": e["to_id"], "kind": e["kind"], "evidence": _j(e["evidence"])} for e in edges if e["from_id"] in keep and e["to_id"] in keep],
            "counts": {"nodes": len(nodes), "edges_total": len(edges), "nodes_total": len(rows)}}


def table(kind: str | None = None, q: str | None = None, limit: int = 500) -> list[dict]:
    up, down = _adjacency(_edges())
    sql, args = "SELECT * FROM lineage_nodes", []
    if kind:
        sql += " WHERE kind = ?"; args.append(kind)
    if q:
        sql += (" AND" if kind else " WHERE") + " (lower(name) LIKE ? OR lower(label) LIKE ?)"; args += [f"%{q.lower()}%"] * 2
    sql += " ORDER BY kind, system, name LIMIT ?"; args.append(min(limit, 2000))
    return [{**_public(r), "upstream": len(up.get(r["id"], [])), "downstream": len(down.get(r["id"], []))} for r in db.q(sql, tuple(args))]


def summary() -> dict:
    by_kind = {r["kind"]: r["n"] for r in db.q("SELECT kind, COUNT(*) AS n FROM lineage_nodes GROUP BY kind")}
    by_source = {r["source"] or "": r["n"] for r in db.q("SELECT source, COUNT(*) AS n FROM lineage_nodes GROUP BY source")}
    edges = db.one("SELECT COUNT(*) AS n FROM lineage_edges")["n"]
    _, down = _adjacency(_edges())
    sugg = None
    for kind in ("report", "flow", "job", "bot", "entity", "table"):
        rows = db.q("SELECT id, label, name FROM lineage_nodes WHERE kind = ?", (kind,))
        if rows:
            best = max(rows, key=lambda r: len(down.get(r["id"], [])) + len([1 for e in _edges() if e["to_id"] == r["id"]]))
            sugg = {"id": best["id"], "label": best["label"] or best["name"], "kind": kind}
            break
    return {"nodes": sum(by_kind.values()), "edges": edges, "by_kind": by_kind, "by_source": by_source, "kinds": KIND_LABEL,
            "synced": float(db.meta("lineage_synced", "0") or 0), "suggested": sugg}


# ------------------------------------------------------------------ API

def _u() -> dict:
    u = auth.current.get()
    if not u:
        raise HTTPException(401, "Sign in.")
    return u


def _builder() -> dict:
    u = _u()
    if not auth.is_dev(u):
        raise HTTPException(403, "Only a BI Dev / Analyst or an Admin can do that.")
    return u


class Tags(BaseModel):
    personal: str | None = None            # personal | anonymised | none
    note: str | None = None


@router.get("/api/lineage/summary")
def api_summary():
    _u(); ensure_synced()
    return summary()


@router.post("/api/lineage/sync")
def api_sync():
    u = _builder()
    return sync_all(u["id"])


@router.get("/api/lineage/search")
def api_search(q: str = "", kind: str | None = None, limit: int = 30):
    _u(); ensure_synced()
    return {"items": search(q, [k for k in (kind or "").split(",") if k], min(limit, 100))}


@router.get("/api/lineage/slice")
def api_slice(id: str, depth: int = 2, direction: str = "both", kinds: str | None = None):  # noqa: A002
    _u(); ensure_synced()
    if direction not in ("both", "up", "down"):
        raise HTTPException(400, "direction is both, up or down.")
    return slice(id, depth, direction, [k for k in (kinds or "").split(",") if k])


@router.get("/api/lineage/graph")
def api_graph(limit: int = 250, kinds: str | None = None):
    _u(); ensure_synced()
    return whole(max(10, min(limit, 1500)), [k for k in (kinds or "").split(",") if k])


@router.get("/api/lineage/path")
def api_path(a: str, b: str):
    _u(); ensure_synced()
    return path(a, b)


@router.get("/api/lineage/table")
def api_table(kind: str | None = None, q: str | None = None, limit: int = 500):
    _u(); ensure_synced()
    return {"items": table(kind, q, limit)}


@router.get("/api/lineage/impact/{nid}")
def api_impact(nid: str):
    _u(); ensure_synced()
    return impact(nid)


@router.get("/api/lineage/node/{nid}")
def api_node(nid: str):
    _u(); ensure_synced()
    n = get(nid)
    if not n:
        raise HTTPException(404, "No such item on the map.")
    return {**n, **neighbours(nid), "impact": impact(nid)}


@router.put("/api/lineage/node/{nid}/tags")
def api_tags(nid: str, body: Tags):
    u = _builder()
    n = get(nid)
    if not n:
        raise HTTPException(404, "No such item on the map.")
    if body.personal not in (None, "personal", "anonymised", "none"):
        raise HTTPException(400, "personal is personal, anonymised or none.")
    props = n["properties"]
    if body.personal:
        props["personal"] = None if body.personal == "none" else body.personal
    if body.note is not None:
        props["note"] = body.note.strip()[:500]
    props["tagged_by"], props["tagged"] = u["id"], time.time()
    db.run("UPDATE lineage_nodes SET properties = ? WHERE id = ?", (json.dumps(props), nid))
    db.audit("lineage.tag", nid, {"personal": body.personal, "note": (body.note or "")[:100]}, u["id"])
    return get(nid)
